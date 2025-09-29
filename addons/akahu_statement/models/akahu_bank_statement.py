# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta, date
import requests
import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
AKAHU_API = "https://api.akahu.io/v1"


def _parse_iso_to_local_naive(iso_str: str, tz_name: str | None) -> datetime:
    if not iso_str:
        aware = fields.Datetime.now()
        return aware.replace(tzinfo=None)

    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        aware = datetime.fromisoformat(s)
    except Exception as e:
        raise UserError(_("Akahu: cannot parse transaction date: %s") % iso_str) from e

    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=pytz.UTC)

    tz = pytz.timezone(tz_name or "UTC")
    local_aware = aware.astimezone(tz)
    return local_aware.replace(tzinfo=None)


class AkahuBankStatement(models.Model):
    _name = 'akahu.bank.statement'
    _description = 'Akahu Bank Statement Import & Reconciliation'

    # ------------------ helpers ------------------

    @api.model
    def _get_headers(self):
        token = self.env['ir.config_parameter'].sudo().get_param('akahu.access_token')
        if not token:
            raise UserError(_("Akahu access token not set (system parameter: akahu.access_token)."))
        return {"Authorization": f"Bearer {token}"}

    @api.model
    def _get_target_journal(self, journal_id=None):
        if journal_id:
            journal = self.env['account.journal'].browse(int(journal_id))
            if not journal or not journal.exists():
                raise UserError(_("Selected bank journal not found."))
            return journal
        jid = self.env['ir.config_parameter'].sudo().get_param('akahu.journal_id')
        if not jid:
            raise UserError(_("Set a bank journal id in system parameter: akahu.journal_id"))
        journal = self.env['account.journal'].browse(int(jid))
        if not journal or not journal.exists():
            raise UserError(_("Bank journal in system parameter not found."))
        return journal

    @api.model
    def _get_clearing_account(self, journal):
        """Prefer journal field; else system param; always browse in the journal's company."""
        # 1) journal field (if present on your build)
        if hasattr(journal, 'clearing_account_id') and journal.clearing_account_id:
            return journal.clearing_account_id

        # 2) system parameter (company-aware + sudo so multi-company never hides it)
        cid = self.env['ir.config_parameter'].sudo().get_param('akahu.clearing_account_id')
        if cid:
            Account = self.env['account.account'].with_context(
                force_company=journal.company_id.id,
                allowed_company_ids=[journal.company_id.id],
            ).sudo()
            acc = Account.browse(int(cid))
            if acc and acc.exists():
                return acc

        raise UserError(_("Configure a Bank Clearing account (journal field or system parameter 'akahu.clearing_account_id')."))

    @api.model
    def _get_or_create_daily_statement(self, journal, day: date):
        Statement = self.env['account.bank.statement']
        st = Statement.search([('journal_id', '=', journal.id), ('date', '=', day)], limit=1)
        if st:
            return st
        return Statement.create({'name': f"{journal.name} {day.isoformat()}", 'date': day, 'journal_id': journal.id})

    @api.model
    def _line_exists(self, journal_id: int, unique_id: str) -> bool:
        if not unique_id:
            return False
        return bool(self.env['account.bank.statement.line'].search_count([
            ('journal_id', '=', journal_id), ('unique_import_id', '=', unique_id),
        ]))

    # Receivable/Payable domain (version-proof)
    def _rp_domain(self, inbound: bool):
        Account = self.env['account.account']
        target = ['receivable'] if inbound else ['payable']

        if 'account_type' in Account._fields:
            sel = dict(Account._fields['account_type'].selection)
            keys = [k for k in sel if any(t in k for t in target)]
            if keys:
                return [('account_id.account_type', 'in', list(set(keys)))]

        if 'internal_type' in Account._fields:
            return [('account_id.internal_type', 'in', target)]

        if 'user_type_id' in Account._fields:
            Type = self.env['account.account.type']
            ids_ = Type.search([('type', 'in', target)]).ids
            if ids_:
                return [('account_id.user_type_id', 'in', ids_)]

        return []

    # ------------------ import ------------------

    @api.model
    def import_akahu_transactions(self, journal_id=None, days_back=90, tz_name=None, page_limit=200):
        headers = self._get_headers()
        journal = self._get_target_journal(journal_id)
        tz_name = tz_name or self.env.user.tz or "UTC"

        since = (fields.Datetime.now() - timedelta(days=int(days_back))).strftime('%Y-%m-%dT%H:%M:%SZ')

        acc_resp = requests.get(f"{AKAHU_API}/accounts", headers=headers, timeout=60)
        try:
            acc_data = acc_resp.json()
        except Exception:
            raise UserError(_("Akahu /accounts response is not JSON: %s") % acc_resp.text)
        accounts = acc_data.get("items", [])
        _logger.info("Akahu: %d account(s) discovered", len(accounts))

        created = 0
        skipped = 0

        for acc in accounts:
            acc_id = acc.get("_id")
            if not acc_id:
                continue

            params = {'start': since, 'limit': page_limit}
            url = f"{AKAHU_API}/accounts/{acc_id}/transactions"

            while True:
                resp = requests.get(url, headers=headers, params=params, timeout=90)
                try:
                    data = resp.json()
                except Exception:
                    raise UserError(_("Akahu /transactions not JSON for account %s: %s") % (acc_id, resp.text))

                items = data.get("items", [])
                if not isinstance(items, list):
                    raise UserError(_("Akahu: unexpected transactions payload for account %s.") % acc_id)

                for tx in items:
                    akahu_id = tx.get("_id") or tx.get("id")
                    if not akahu_id:
                        skipped += 1
                        continue
                    if self._line_exists(journal.id, akahu_id):
                        skipped += 1
                        continue

                    raw_date = tx.get("date") or tx.get("created_at")
                    local_dt = _parse_iso_to_local_naive(raw_date, tz_name)
                    day = local_dt.date()

                    st = self._get_or_create_daily_statement(journal, day)

                    description = (tx.get("description") or tx.get("details") or "").strip() or "Akahu"
                    counterpart = (tx.get("counterparty") or {}).get("name") or ""
                    amount = float(tx.get("amount") or 0.0)

                    vals = {
                        'statement_id': st.id,
                        'date': day,
                        'payment_ref': description,
                        'name': description,
                        'partner_name': counterpart or False,
                        'amount': amount,
                        'journal_id': journal.id,
                        'unique_import_id': akahu_id,
                    }
                    stl = self.env['account.bank.statement.line'].create(vals)
                    created += 1

                    # DRAFT JE (Bank ↔ Clearing)
                    clearing = self._get_clearing_account(journal)
                    bank = journal.default_account_id
                    if not bank:
                        raise UserError(_("Bank journal %s needs a Default Account.") % journal.display_name)

                    ref = f"AKAHU {akahu_id} - {description}"
                    amt_abs = abs(amount)

                    if amount > 0:
                        move_lines = [
                            {'name': description, 'account_id': bank.id,     'debit': amt_abs, 'credit': 0.0},
                            {'name': description, 'account_id': clearing.id, 'debit': 0.0,     'credit': amt_abs},
                        ]
                    else:
                        move_lines = [
                            {'name': description, 'account_id': clearing.id, 'debit': amt_abs, 'credit': 0.0},
                            {'name': description, 'account_id': bank.id,     'debit': 0.0,     'credit': amt_abs},
                        ]

                    draft_vals = {
                        'move_type': 'entry',
                        'date': day,
                        'journal_id': journal.id,
                        'ref': ref[:140],
                        'line_ids': [(0, 0, v) for v in move_lines],
                    }
                    draft_move = self.env['account.move'].create(draft_vals)
                    if hasattr(stl, 'journal_entry_ids'):
                        stl.write({'journal_entry_ids': [(4, draft_move.id)]})

                next_cursor = None
                cursor_obj = data.get("cursor")
                if isinstance(cursor_obj, dict):
                    next_cursor = cursor_obj.get("next")
                if next_cursor:
                    params = {'cursor': next_cursor}
                    continue

                if len(items) >= page_limit:
                    _logger.info("Akahu: page returned %d items (==limit) but no cursor; stopping.", len(items))
                break

        _logger.info("Akahu import complete: %d created, %d skipped (existing).", created, skipped)
        return {'created': created, 'skipped': skipped}

    # ------------------ auto-reconcile ------------------

    @api.model
    def auto_reconcile_bank_lines(self, journal_id=None, max_days=7, amount_tolerance=0.50, require_text_hint=False):
        journal = self._get_target_journal(journal_id)
        Move = self.env['account.move']
        AML  = self.env['account.move.line']
        Partner = self.env['res.partner']

        if not journal.default_account_id:
            raise UserError(_("Bank journal %s has no Default Account configured.") % journal.display_name)

        since = fields.Date.today() - timedelta(days=int(max_days))

        st_lines = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', journal.id),
            ('date', '>=', since),
        ], order='date asc', limit=1000)

        reconciled_count, ambiguous, missing = 0, 0, 0

        for stl in st_lines:
            if any(ml.reconciled for ml in getattr(stl, 'move_line_ids', [])):
                continue

            amount = float(stl.amount or 0.0)
            if abs(amount) < 1e-9:
                continue

            inbound = amount > 0

            partner = stl.partner_id if getattr(stl, 'partner_id', False) else None
            if not partner and getattr(stl, 'partner_name', None):
                partner = Partner.search([('name', 'ilike', stl.partner_name)], limit=1)

            posted_field = 'parent_state' if 'parent_state' in AML._fields else 'move_id.state'

            domain = [
                ('company_id', '=', stl.company_id.id),
                (posted_field, '=', 'posted'),
                ('reconciled', '=', False),
            ] + self._rp_domain(inbound)

            if partner:
                domain.append(('partner_id', '=', partner.id))

            candidates = AML.search(domain, limit=200)

            wanted = abs(amount)
            keep = []
            for line in candidates:
                if getattr(stl, 'currency_id', False) and line.currency_id and line.currency_id == stl.currency_id:
                    res = abs(line.amount_residual_currency)
                else:
                    res = abs(line.amount_residual)
                if abs(res - wanted) <= amount_tolerance:
                    keep.append(line)

            if require_text_hint and getattr(stl, 'payment_ref', None):
                ref_l = (stl.payment_ref or "").lower()
                hinted = []
                for l in keep:
                    blob = " ".join([
                        l.move_id.ref or "",
                        l.move_id.name or "",
                        l.name or "",
                        getattr(l.move_id, 'invoice_payment_ref', '') or "",
                    ]).lower()
                    if ref_l and ref_l in blob:
                        hinted.append(l)
                if hinted:
                    keep = hinted

            if len(keep) == 0:
                missing += 1
                continue
            if len(keep) > 1:
                ambiguous += 1
                continue

            counterpart = keep[0]
            bank_account = journal.default_account_id
            clearing = self._get_clearing_account(journal)
            label = stl.payment_ref or stl.name or '/'
            amt = abs(amount)

            draft_move = False
            if hasattr(stl, 'journal_entry_ids'):
                draft_move = stl.journal_entry_ids.filtered(lambda m: m.state == 'draft' and m.journal_id == journal)[:1]
            if not draft_move:
                uid = getattr(stl, 'unique_import_id', '') or ''
                if uid:
                    draft_move = Move.search([
                        ('journal_id', '=', journal.id),
                        ('state', '=', 'draft'),
                        ('ref', 'ilike', uid),
                    ], limit=1)

            if not draft_move:
                if inbound:
                    move_lines = [
                        {'name': label, 'account_id': bank_account.id,           'debit': amt, 'credit': 0.0},
                        {'name': label, 'account_id': counterpart.account_id.id, 'debit': 0.0, 'credit': amt, 'partner_id': counterpart.partner_id.id},
                    ]
                else:
                    move_lines = [
                        {'name': label, 'account_id': bank_account.id,           'debit': 0.0, 'credit': amt},
                        {'name': label, 'account_id': counterpart.account_id.id, 'debit': amt, 'credit': 0.0, 'partner_id': counterpart.partner_id.id},
                    ]
                move_vals = {
                    'move_type': 'entry',
                    'date': stl.date,
                    'journal_id': journal.id,
                    'ref': label,
                    'line_ids': [(0, 0, v) for v in move_lines],
                }
                move = Move.create(move_vals)
            else:
                move = draft_move
                clearing_lines = move.line_ids.filtered(lambda l: l.account_id == clearing)
                if not clearing_lines:
                    raise UserError(_("Expected a Clearing line in draft move %s but none found.") % move.display_name)

                if inbound:
                    target_line = clearing_lines.filtered(lambda l: l.credit > 0.0)[:1] or clearing_lines[:1]
                    target_line.write({'account_id': counterpart.account_id.id, 'partner_id': counterpart.partner_id.id})
                else:
                    target_line = clearing_lines.filtered(lambda l: l.debit > 0.0)[:1] or clearing_lines[:1]
                    target_line.write({'account_id': counterpart.account_id.id, 'partner_id': counterpart.partner_id.id})

                if not move.ref or 'AKAHU' in (move.ref or ''):
                    move.ref = label

            move.action_post()

            new_leg = move.line_ids.filtered(lambda l: l.account_id == counterpart.account_id and not l.reconciled)
            (new_leg + counterpart).reconcile()

            if hasattr(stl, 'journal_entry_ids') and move not in stl.journal_entry_ids:
                stl.write({'journal_entry_ids': [(4, move.id)]})

            reconciled_count += 1

        _logger.info(
            "Akahu auto-reconcile: %d reconciled, %d ambiguous, %d missing (journal=%s).",
            reconciled_count, ambiguous, missing, journal.display_name
        )
        return {'reconciled': reconciled_count, 'ambiguous': ambiguous, 'missing': missing}
