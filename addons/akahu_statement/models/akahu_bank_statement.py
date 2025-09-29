# -*- coding: utf-8 -*-  # file encoding (ok to keep)

# ---------------------------------------------
# STANDARD LIBS & THIRD-PARTY
# ---------------------------------------------
import logging                         # for writing messages to Odoo logs
from datetime import datetime, timedelta, date  # date/time helpers
import requests                        # to call the Akahu HTTP API
import pytz                            # to convert UTC datetimes to local timezone

# ---------------------------------------------
# ODOO IMPORTS
# ---------------------------------------------
from odoo import api, fields, models, _  # Odoo ORM base, fields, decorators, translation _
from odoo.exceptions import UserError     # user-facing error (shows in UI/logs)

# ---------------------------------------------
# LOGGING SETUP
# ---------------------------------------------
_logger = logging.getLogger(__name__)     # logger named after this module (used by _logger.info, etc.)

# ---------------------------------------------
# AKAHU API BASE ENDPOINT
# ---------------------------------------------
AKAHU_API = "https://api.akahu.io/v1"     # base URL for all Akahu API calls


# ======================================================================
# UTILITY: PARSE ISO STRING -> LOCAL *NAIVE* DATETIME
# Why: Akahu gives UTC timestamps; we bucket lines per *local calendar day*.
# Steps: parse -> ensure tz-aware -> convert to user's tz -> drop tzinfo.
# ======================================================================
def _parse_iso_to_local_naive(iso_str: str, tz_name: str | None) -> datetime:
    """
    Example input: '2025-09-19T11:22:33Z' or '2025-09-19T11:22:33+00:00'
    Returns a *naive* datetime in local tz so that .date() matches local day.
    """
    if not iso_str:
        aware = fields.Datetime.now()     # Odoo helper returns aware dt in user tz
        return aware.replace(tzinfo=None) # make it naive for Odoo's date fields

    s = iso_str.strip()
    if s.endswith("Z"):                   # normalize trailing Z to +00:00 for fromisoformat
        s = s[:-1] + "+00:00"

    try:
        aware = datetime.fromisoformat(s) # parse to datetime (aware if offset present)
    except Exception as e:
        # Give a friendly error with the raw value for debugging
        raise UserError(_("Akahu: cannot parse transaction date: %s") % iso_str) from e

    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=pytz.UTC)  # if no tz, assume UTC

    tz = pytz.timezone(tz_name or "UTC")        # prefer user's tz, else UTC
    local_aware = aware.astimezone(tz)          # convert to local tz
    return local_aware.replace(tzinfo=None)     # return naive local dt


# ======================================================================
# MAIN SERVICE MODEL (CRON/WIZARD ENTRY POINTS LIVE HERE)
# ======================================================================
class AkahuBankStatement(models.Model):
    """
    Public API used by cron and wizard:

    1) import_akahu_transactions(...)
       - Pull Akahu transactions, bucket into **daily** bank statements,
         de-dup by unique_import_id, and (Option B) create a **DRAFT** JE per txn:
           • Inbound(+) :  Dr Bank / Cr Clearing
           • Outbound(-):  Dr Clearing / Cr Bank
         - Link the draft JE to the bank statement line (traceability).
         >>> This is the "DRAFT" stage of the Draft → Posted cycle.

    2) auto_reconcile_bank_lines(...)
       - Find exactly one open AR/AP line per statement line (amount ± tolerance,
         optional text hint). If found:
           • Replace the Clearing leg with AR/AP + partner,
           • POST the move (state: draft → posted),
           • RECONCILE the AR/AP leg with the matched item.
         - If 0 or >1 candidates, leave the JE in DRAFT (manual review).
         >>> This is the "POSTED" stage when a clean match exists.
    """

    _name = 'akahu.bank.statement'
    _description = 'Akahu Bank Statement Import & Reconciliation'

    # ------------------------------------------------------------------
    # HELPERS (config + common utilities)
    # ------------------------------------------------------------------
    @api.model
    def _get_headers(self):
        """
        Build HTTP headers for Akahu calls using system parameter
        'akahu.access_token'. Fail fast if missing.
        """
        token = self.env['ir.config_parameter'].sudo().get_param('akahu.access_token')
        if not token:
            raise UserError(_("Akahu access token not set (system parameter: akahu.access_token)."))
        return {"Authorization": f"Bearer {token}"}

    @api.model
    def _get_target_journal(self, journal_id=None):
        """
        Choose the Bank Journal:
          - if a journal_id is provided (wizard/cron), use it,
          - else fall back to system parameter 'akahu.journal_id'.
        """
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
        Resolve the **Bank Clearing/Suspense** account used at the DRAFT stage.
        Priority:
          1) journal.clearing_account_id (if you added that field),
          2) system parameter 'akahu.clearing_account_id' (account.account id).
        """
        # 1) Prefer a specific field on the journal if present in your deployment
        if hasattr(journal, 'clearing_account_id') and journal.clearing_account_id:
            return journal.clearing_account_id

        # 2) Fallback to system parameter
        cid = self.env['ir.config_parameter'].sudo().get_param('akahu.clearing_account_id')
        if cid:
            acc = self.env['account.account'].browse(int(cid))
            if acc and acc.exists():
                return acc

        # No config → no draft cycle possible
        raise UserError(_("Configure a Bank Clearing account (journal field or system parameter 'akahu.clearing_account_id')."))

    @api.model
    def _get_or_create_daily_statement(self, journal, day: date):
        """
        Guarantee a single bank statement per (journal, day).
        """
        Statement = self.env['account.bank.statement']
        st = Statement.search([
            ('journal_id', '=', journal.id),
            ('date', '=', day),
        ], limit=1)
        if st:
            return st
        return Statement.create({
            'name': f"{journal.name} {day.isoformat()}",
            'date': day,
            'journal_id': journal.id,
        })

    @api.model
    def _line_exists(self, journal_id: int, unique_id: str) -> bool:
        """
        De-dup protection: if a line with this unique_import_id already exists
        in this journal, we skip creating it again.
        """
        if not unique_id:
            return False
        return bool(self.env['account.bank.statement.line'].search_count([
            ('journal_id', '=', journal_id),
            ('unique_import_id', '=', unique_id),
        ]))

    # -------- NEW: version-proof receivable/payable domain helper --------
    def _rp_domain(self, inbound: bool):
        """
        Return a domain that targets receivable/payable accounts, compatible with different Odoo schemas.
        inbound=True  -> receivable
        inbound=False -> payable
        """
        Account = self.env['account.account']
        target = ['receivable'] if inbound else ['payable']

        # Newer Odoo: 'account_type' selection on account.account
        if 'account_type' in Account._fields:
            sel = dict(Account._fields['account_type'].selection)
            keys = []
            for k in sel.keys():
                # accept keys containing 'receivable' / 'payable' (e.g. 'asset_receivable', 'liability_payable')
                if any(t in k for t in target):
                    keys.append(k)
            if keys:
                return [('account_id.account_type', 'in', list(set(keys)))]

        # Older Odoo: 'internal_type' selection ('receivable', 'payable', ...)
        if 'internal_type' in Account._fields:
            return [('account_id.internal_type', 'in', target)]

        # Fallback: via account.account.type.type == receivable/payable
        if 'user_type_id' in Account._fields:
            Type = self.env['account.account.type']
            ids_ = Type.search([('type', 'in', target)]).ids
            if ids_:
                return [('account_id.user_type_id', 'in', ids_)]

        # Last resort: no additional filter
        return []

    # ------------------------------------------------------------------
    # ENTRY POINT #1: IMPORT (CRON/SERVER ACTION & WIZARD USE THIS)
    # Draft → Posted cycle: this method creates **DRAFT** JEs only.
    # ------------------------------------------------------------------
    @api.model
    def import_akahu_transactions(self, journal_id=None, days_back=90, tz_name=None, page_limit=200):
        """
        Pull Akahu transactions (last N days), bucket them by local date into
        daily bank statements, de-dup by unique_import_id, and (Option B) create
        a **DRAFT** JE per transaction (Bank ↔ Clearing) linked to the BSL.
        >>> NOTE: We do NOT post here. Moves remain state='draft'.
        """
        headers = self._get_headers()               # build Akahu auth header
        journal = self._get_target_journal(journal_id)
        tz_name = tz_name or self.env.user.tz or "UTC"

        # Starting timestamp = "now - days_back" (UTC, Akahu expects ISO)
        since = (fields.Datetime.now() - timedelta(days=int(days_back))).strftime('%Y-%m-%dT%H:%M:%SZ')

        # 1) Get all Akahu accounts the token can see
        acc_resp = requests.get(f"{AKAHU_API}/accounts", headers=headers, timeout=60)
        try:
            acc_data = acc_resp.json()
        except Exception:
            raise UserError(_("Akahu /accounts response is not JSON: %s") % acc_resp.text)
        accounts = acc_data.get("items", [])
        _logger.info("Akahu: %d account(s) discovered", len(accounts))

        created = 0
        skipped = 0

        # 2) For each account, page through transactions
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

                # 3) For each transaction → create BSL + **DRAFT** JE (Bank ↔ Clearing)
                for tx in items:
                    akahu_id = tx.get("_id") or tx.get("id")
                    if not akahu_id:
                        skipped += 1
                        continue
                    if self._line_exists(journal.id, akahu_id):
                        skipped += 1
                        continue

                    # Convert transaction timestamp to local naive, then take the calendar day
                    raw_date = tx.get("date") or tx.get("created_at")
                    local_dt = _parse_iso_to_local_naive(raw_date, tz_name)
                    day = local_dt.date()

                    # One statement per (journal, day)
                    st = self._get_or_create_daily_statement(journal, day)

                    # Human-friendly info for the statement line
                    description = (tx.get("description") or tx.get("details") or "").strip() or "Akahu"
                    counterpart = (tx.get("counterparty") or {}).get("name") or ""
                    amount = float(tx.get("amount") or 0.0)  # + inbound, - outbound

                    # Create the bank statement line (BSL)
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

                    # === DRAFT → part 1: Create a **DRAFT** JE mirroring the cash movement ===
                    # • Inbound (+):  Dr Bank / Cr Clearing
                    # • Outbound(-):  Dr Clearing / Cr Bank
                    # (No posting here, so state stays 'draft')
                    clearing = self._get_clearing_account(journal)
                    bank = journal.default_account_id
                    if not bank:
                        raise UserError(_("Bank journal %s needs a Default Account.") % journal.display_name)

                    ref = f"AKAHU {akahu_id} - {description}"  # searchable link to this txn
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
                        'date': day,                       # same day as BSL
                        'journal_id': journal.id,          # bank journal
                        'ref': ref[:140],                  # short ref
                        'line_ids': [(0, 0, v) for v in move_lines],
                    }
                    draft_move = self.env['account.move'].create(draft_vals)  # <-- stays DRAFT (no .action_post())
                    # Link JE back to the bank line if the relation exists in your Odoo
                    if hasattr(stl, 'journal_entry_ids'):
                        stl.write({'journal_entry_ids': [(4, draft_move.id)]})

                # 4) Pagination: follow cursor if present; otherwise stop.
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

    # ------------------------------------------------------------------
    # ENTRY POINT #2: AUTO-RECONCILE (CRON/SERVER ACTION & WIZARD)
    # Draft → Posted cycle: this method moves **DRAFT** to **POSTED** on clean matches.
    # ------------------------------------------------------------------
    @api.model
    def auto_reconcile_bank_lines(self, journal_id=None, max_days=7, amount_tolerance=0.50, require_text_hint=False):
        """
        Goal: For recent BSLs, find exactly one matching open AR/AP line and:
          1) Transform the associated **DRAFT** JE by replacing Clearing with AR/AP (+partner),
          2) POST the move (state: draft → posted),
          3) RECONCILE the AR/AP leg with the matched open item.

        If 0 or >1 candidates → safety first: leave the JE **in DRAFT** (manual review).
        """
        journal = self._get_target_journal(journal_id)
        Move = self.env['account.move']
        AML  = self.env['account.move.line']
        Partner = self.env['res.partner']

        if not journal.default_account_id:
            raise UserError(_("Bank journal %s has no Default Account configured.") % journal.display_name)

        # Only process lines from the last N days (keeps job fast/safe)
        since = fields.Date.today() - timedelta(days=int(max_days))

        st_lines = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', journal.id),
            ('date', '>=', since),
        ], order='date asc', limit=1000)

        reconciled_count = 0
        ambiguous = 0
        missing = 0

        for stl in st_lines:
            # Skip if already reconciled (some versions expose stl.move_line_ids)
            if any(ml.reconciled for ml in getattr(stl, 'move_line_ids', [])):
                continue

            amount = float(stl.amount or 0.0)
            if abs(amount) < 1e-9:
                continue

            inbound = amount > 0

            # Try to pin the partner (from field or fuzzy by name)
            partner = stl.partner_id if getattr(stl, 'partner_id', False) else None
            if not partner and getattr(stl, 'partner_name', None):
                partner = Partner.search([('name', 'ilike', stl.partner_name)], limit=1)

            # Use parent_state if present, else move_id.state (version-proof)
            posted_field = 'parent_state' if 'parent_state' in AML._fields else 'move_id.state'

            # Build candidate domain with version-proof receivable/payable filter
            domain = [
                ('company_id', '=', stl.company_id.id),
                (posted_field, '=', 'posted'),
                ('reconciled', '=', False),
            ] + self._rp_domain(inbound)

            if partner:
                domain.append(('partner_id', '=', partner.id))

            candidates = AML.search(domain, limit=200)

            # Amount screening (currency-aware when possible)
            wanted = abs(amount)
            keep = []
            for line in candidates:
                if getattr(stl, 'currency_id', False) and line.currency_id and line.currency_id == stl.currency_id:
                    res = abs(line.amount_residual_currency)
                else:
                    res = abs(line.amount_residual)
                if abs(res - wanted) <= amount_tolerance:
                    keep.append(line)

            # Optional text prefilter: require payment_ref to appear in invoice/bill refs
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

            # Decide: 0 → leave draft, >1 → leave draft, ==1 → transform & post
            if len(keep) == 0:
                missing += 1
                continue
            if len(keep) > 1:
                ambiguous += 1
                continue

            # Exactly one candidate → we will POST this transaction (draft → posted)
            counterpart = keep[0]
            bank_account = journal.default_account_id
            clearing = self._get_clearing_account(journal)
            label = stl.payment_ref or stl.name or '/'
            amt = abs(amount)

            # 1) Find the **DRAFT** move we created at import (linked via journal_entry_ids or ref)
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

            # 2) If no draft found (edge case), create a new move (old behavior fallback)
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
                move = Move.create(move_vals)   # created as DRAFT, will post next
            else:
                move = draft_move
                # 3) Transform **DRAFT** move by swapping the Clearing leg → AR/AP + partner
                #    • inbound: Clearing is the CREDIT line → becomes Receivable (credit)
                #    • outbound: Clearing is the DEBIT line → becomes Payable (debit)
                clearing_lines = move.line_ids.filtered(lambda l: l.account_id == clearing)
                if not clearing_lines:
                    raise UserError(_("Expected a Clearing line in draft move %s but none found.") % move.display_name)

                if inbound:
                    target_line = clearing_lines.filtered(lambda l: l.credit > 0.0)[:1] or clearing_lines[:1]
                    target_line.write({
                        'account_id': counterpart.account_id.id,
                        'partner_id': counterpart.partner_id.id,
                    })
                else:
                    target_line = clearing_lines.filtered(lambda l: l.debit > 0.0)[:1] or clearing_lines[:1]
                    target_line.write({
                        'account_id': counterpart.account_id.id,
                        'partner_id': counterpart.partner_id.id,
                    })

                # Clean reference if still the import ref
                if not move.ref or 'AKAHU' in (move.ref or ''):
                    move.ref = label

            # 4) POST the move  >>> HERE the state changes: draft → posted <<<
            move.action_post()

            # 5) Reconcile the AR/AP leg from this move with the matched open item
            new_leg = move.line_ids.filtered(lambda l: l.account_id == counterpart.account_id and not l.reconciled)
            (new_leg + counterpart).reconcile()

            # 6) Ensure the JE is linked back to the bank statement line (traceability)
            if hasattr(stl, 'journal_entry_ids') and move not in stl.journal_entry_ids:
                stl.write({'journal_entry_ids': [(4, move.id)]})

            reconciled_count += 1

        # Summary in logs for observability
        _logger.info(
            "Akahu auto-reconcile: %d reconciled, %d ambiguous, %d missing (journal=%s).",
            reconciled_count, ambiguous, missing, journal.display_name
        )
        return {
            'reconciled': reconciled_count,
            'ambiguous': ambiguous,
            'missing': missing,
        }
