# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta, date

import pytz
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# --- DB uniqueness handling (works across Odoo psycopg2/DB variants) ---
try:
    from psycopg2.errors import UniqueViolation  # type: ignore
except Exception:  # pragma: no cover
    UniqueViolation = Exception
try:
    from odoo.sql_db import IntegrityError  # Odoo-wrapped DB error
except Exception:  # pragma: no cover
    IntegrityError = Exception

_logger = logging.getLogger(__name__)
AKAHU_API = "https://api.akahu.io/v1"


# ---------------------------------------------------------
# Utilities
# ---------------------------------------------------------
def _parse_iso_to_local_naive(iso_str: str, tz_name: str | None) -> datetime:
    """Parse ISO string (UTC or with tz) and return *naive* datetime in user's tz."""
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


# ---------------------------------------------------------
# Optional toggle on the Bank Journal (kept for clarity/UX)
# ---------------------------------------------------------
class AccountJournalAkahu(models.Model):
    _inherit = 'account.journal'

    x_defer_bank_posting = fields.Boolean(
        string="Defer Bank Move Posting",
        help="Keep liquidity moves created from bank statement lines in DRAFT "
             "until the Akahu reconciliation job explicitly posts them.",
        default=True,
    )


# ---------------------------------------------------------
# Keep liquidity moves from bank lines in DRAFT (no auto-post)
# ---------------------------------------------------------
class StatementLineDeferPosting(models.Model):
    _inherit = 'account.bank.statement.line'

    def _prepare_move_values(self):
        """Force the liquidity move created from a statement line to stay DRAFT."""
        vals = super()._prepare_move_values()
        if 'auto_post' in self.env['account.move']._fields:
            vals['auto_post'] = 'no'
        return vals

    def _synchronize_to_moves(self, changed_fields):
        """Safety belt: if anything posted the move, bring it back to draft."""
        res = super()._synchronize_to_moves(changed_fields)
        for line in self:
            move = getattr(line, 'move_id', False)
            if move and move.state == 'posted':
                move.button_draft()
        return res

# ---------------------------------------------------------
# SQL-level uniqueness protection (race-condition safe)
# ---------------------------------------------------------
class StatementLineAkahuUnique(models.Model):
    _inherit = 'account.bank.statement.line'

    unique_import_id = fields.Char(index=True)

    _sql_constraints = [
        ('unique_import_id_uniq',
         'unique(unique_import_id)',
         'This Akahu transaction has already been imported.')
    ]

# ---------------------------------------------------------
# Main Service: Import + Reconcile
# ---------------------------------------------------------
class AkahuBankStatement(models.Model):
    _name = 'akahu.bank.statement'
    _description = 'Akahu Bank Statement Import & Reconciliation'

    # ------------------ helpers ------------------
    @api.model
    def _get_headers(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('akahu.access_token')
        app_id = ICP.get_param('akahu.app_id')  # REQUIRED by Akahu
        if not token:
            raise UserError(_("Akahu access token not set (system parameter: akahu.access_token)."))
        if not app_id:
            raise UserError(_("Akahu App ID not set (system parameter: akahu.app_id)."))
        return {
            "Authorization": f"Bearer {token}",
            "X-Akahu-ID": app_id,  # correct casing
        }

    def _json_or_raise(self, resp, endpoint: str):
        """Turn HTTP/network errors and non-JSON bodies into clear UserErrors."""
        try:
            resp.raise_for_status()
        except requests.RequestException as e:
            raise UserError(_("Akahu request failed (%s): %s") % (endpoint, getattr(resp, "text", str(e))[:500]))
        try:
            return resp.json()
        except Exception:
            raise UserError(_("Akahu returned non-JSON for %s: %s") % (endpoint, getattr(resp, "text", "")[:500]))

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
        """
        Prefer journal field; else system param; always browse in the journal's company.
        Not strictly required to create the draft move anymore (we rewrite the non-bank leg),
        but we keep this to help admins configure things properly.
        """
        if hasattr(journal, 'clearing_account_id') and journal.clearing_account_id:
            return journal.clearing_account_id

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

    # --- GLOBAL duplicate check (NOT scoped by journal) ---
    @api.model
    def _line_exists(self, unique_id: str) -> bool:
        return bool(unique_id) and bool(
            self.env['account.bank.statement.line']
            .sudo()
            .search_count([('unique_import_id', '=', unique_id)])
        )


    def _rp_domain(self, inbound: bool):
        """Version-proof receivable/payable domain."""
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
        """
        Import Akahu transactions and create bank statement lines ONLY.
        The liquidity moves created by Odoo for these lines are forced to DRAFT.
        Idempotent: safe to re-run (duplicates are skipped).
        """
        headers = self._get_headers()
        journal = self._get_target_journal(journal_id)
        tz_name = tz_name or self.env.user.tz or "UTC"

        since_dt = datetime.utcnow() - timedelta(days=int(days_back))
        since = since_dt.strftime('%Y-%m-%dT%H:%M:%SZ')


        acc_resp = requests.get(f"{AKAHU_API}/accounts", headers=headers, timeout=60)
        acc_data = self._json_or_raise(acc_resp, "/accounts")
        accounts = acc_data.get("items", []) or []
        _logger.info("Akahu: %d account(s) discovered", len(accounts))
        _logger.warning("AKAHU DEBUG → accounts from API: %s", accounts)
        # Optional: restrict to a specific Akahu account via system parameter
        only_acc = (self.env['ir.config_parameter']
            .sudo()
            .get_param('akahu.account_id') or '').strip()
  # e.g. "acc_abc123"
        if only_acc:
            accounts = [a for a in accounts if (a.get('_id') or '') == only_acc]
            if not accounts:
                _logger.warning("Akahu: configured account %s not found in /accounts", only_acc)

        created = 0
        skipped = 0

        for acc in accounts:
            acc_id = acc.get("_id")
            if not acc_id:
                continue

            params = {'limit': page_limit}
            url = f"{AKAHU_API}/accounts/{acc_id}/transactions"

            while True:
                _logger.warning(
                    "AKAHU DEBUG → requesting transactions for %s with params=%s",
                    acc_id, params
                )
                resp = requests.get(url, headers=headers, params=params, timeout=90)
                data = self._json_or_raise(resp, f"/accounts/{acc_id}/transactions")

                items = data.get("items", []) or []
                _logger.warning(
                    "AKAHU DEBUG → API returned %s transactions",
                    len(items)                
                )

                if not isinstance(items, list):
                    raise UserError(_("Akahu: unexpected transactions payload for account %s.") % acc_id)

                for tx in items:
                    akahu_id = tx.get("_id") or tx.get("id")
                    if not akahu_id:
                        skipped += 1
                        continue

                    # Global duplicate check (covers all journals/companies)
                    if self._line_exists(akahu_id):
                        skipped += 1
                        continue

                    raw_date = tx.get("date") or tx.get("created_at")
                    local_dt = _parse_iso_to_local_naive(raw_date, tz_name)
                    day = local_dt.date()

                    st = self._get_or_create_daily_statement(journal, day)

                    description = (tx.get("description") or tx.get("details") or "").strip() or "Akahu"
                    counterpart = (tx.get("counterparty") or {}).get("name") or ""
                    amount = float(tx.get("amount") or 0.0)
                    tx_type = tx.get("type")

                    if tx_type == "DEBIT":
                        amount = -abs(amount)
                    elif tx_type == "CREDIT":
                        amount = abs(amount)


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

                    # Savepoint: ignore concurrent/legacy duplicates safely
                    with self.env.cr.savepoint():
                        try:
                            self.env['account.bank.statement.line'].create(vals)
                            created += 1
                        except (IntegrityError, UniqueViolation):
                            skipped += 1
                            _logger.info("Akahu: duplicate unique_import_id %s — skipped.", akahu_id)

                cursor_obj = data.get("cursor")
                next_cursor = cursor_obj.get("next") if isinstance(cursor_obj, dict) else None
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
        """
        For each bank statement line:
          - Find a single matching posted AR/AP open item within tolerance.
          - If found, transform the line's DRAFT liquidity move:
            replace the non-bank leg with that AR/AP (and partner),
            POST the move, then RECONCILE (exact pair).
          - If zero / multiple matches, leave the move in DRAFT.
        """
        journal = self._get_target_journal(journal_id)
        Move = self.env['account.move']
        AML = self.env['account.move.line']
        Partner = self.env['res.partner']

        if not journal.default_account_id:
            raise UserError(_("Bank journal %s has no Default Account configured.") % journal.display_name)

        since = fields.Date.today() - timedelta(days=int(max_days))

        st_lines = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', journal.id),
            ('date', '>=', since),
        ], order='date asc')

        reconciled_count, ambiguous, missing = 0, 0, 0

        for stl in st_lines:
            # already reconciled?
            if any(ml.reconciled for ml in getattr(stl, 'move_line_ids', [])):
                continue

            amount = float(stl.amount or 0.0)
            if abs(amount) < 1e-9:
                continue

            inbound = amount > 0
            wanted = abs(amount)

            # partner hint
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

            # amount tolerance (+ optional text hint)
            keep = []
            for line in candidates:
                if getattr(stl, 'currency_id', False) and line.currency_id and line.currency_id == stl.currency_id:
                    res = abs(line.amount_residual_currency)
                else:
                    res = abs(line.amount_residual)
                if 0 < wanted <= res + amount_tolerance:
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

            # decide
            if len(keep) == 0:
                missing += 1
                continue
            if len(keep) > 1:
                ambiguous += 1
                continue

            counterpart = keep[0]  # the AR/AP open item we will reconcile to
            bank_account = journal.default_account_id

            # --- find the draft liquidity move attached to the statement line
            draft_move = None
            if hasattr(stl, 'move_id') and stl.move_id and stl.move_id.state == 'draft':
                draft_move = stl.move_id
            if not draft_move and hasattr(stl, 'journal_entry_ids'):
                draft_move = stl.journal_entry_ids.filtered(lambda m: m.state == 'draft' and m.journal_id == journal)[:1]
            if not draft_move:
                # no draft liquidity move found → skip (do NOT create a second move)
                missing += 1
                continue

            # --- rewrite the non-bank leg to AR/AP + partner
            bank_lines = draft_move.line_ids.filtered(lambda l: l.account_id == bank_account)
            other_lines = draft_move.line_ids - bank_lines or draft_move.line_ids
            label = stl.payment_ref or stl.name or '/'
            if not draft_move.ref:
                draft_move.ref = label[:140]

            for ol in other_lines:
                ol.write({
                    'account_id': counterpart.account_id.id,
                    'partner_id': counterpart.partner_id.id,
                })

            # --- post the move (after account/partner rewrite)
            if draft_move.state == 'draft':
                draft_move.action_post()

            # Ensure partner also on the bank leg (helps some builds/views)
            for bl in bank_lines:
                if not bl.partner_id:
                    bl.write({'partner_id': counterpart.partner_id.id})

            def _signed_amt_and_residual(l):
                """Return (signed_amount, residual_abs) in correct currency context."""
                if stl.currency_id and l.currency_id and l.currency_id == stl.currency_id:
                    signed = l.amount_currency           # signed in line currency
                    residual = abs(l.amount_residual_currency)
                else:
                    signed = l.balance                   # signed in company currency
                    residual = abs(l.amount_residual)
                return signed, residual

            tol = float(amount_tolerance or 0.0)

            # counterpart.balance > 0 means debit line (receivable), < 0 credit (payable)
            def _is_matching_bank_arap_line(l):
                if l.account_id != counterpart.account_id:
                    return False
                if l.partner_id != counterpart.partner_id:
                    return False
                return not l.reconciled and abs(_signed_amt_and_residual(l)[1] - wanted) <= tol     

            bank_arap_leg = (draft_move.line_ids.filtered(_is_matching_bank_arap_line))[:1]
            if not bank_arap_leg:
                _logger.warning(
                    "Akahu: could not identify AR/AP leg on bank move %s; counterpart line=%s amount=%s tol=%s",
                    draft_move.display_name, counterpart.id, wanted, tol
                )
                missing += 1
                continue

            # --- reconcile the exact pair only ---
            (bank_arap_leg + counterpart).reconcile()

            # ensure link back for traceability
            if hasattr(stl, 'journal_entry_ids') and draft_move not in stl.journal_entry_ids:
                stl.write({'journal_entry_ids': [(4, draft_move.id)]})

            # Optional: log resulting invoice payment state
            inv = counterpart.move_id
            try:
                inv.invalidate_recordset(['payment_state', 'amount_residual'])
            except Exception:
                pass
            _logger.info(
                "Akahu: reconciled bank %s line %s with invoice line %s → invoice %s payment_state=%s residual=%.2f",
                draft_move.name or draft_move.id,
                bank_arap_leg.id, counterpart.id,
                inv.name or inv.id, getattr(inv, 'payment_state', 'n/a'),
                float(getattr(inv, 'amount_residual', 0.0)),
            )

            reconciled_count += 1

        _logger.info(
            "Akahu auto-reconcile: %d reconciled, %d ambiguous, %d missing (journal=%s).",
            reconciled_count, ambiguous, missing, journal.display_name
        )
        return {'reconciled': reconciled_count, 'ambiguous': ambiguous, 'missing': missing}
