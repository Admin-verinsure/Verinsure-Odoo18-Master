# -*- coding: utf-8 -*-
import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

_logger = logging.getLogger(__name__)

PAYROLL_ACCOUNT_CODES = ['820', '825', '830', '835', '840', '9500', '9510', '9520']

# CRITICAL FIX 1: Tolerance constant for float-safe amount comparisons.
# IEEE 754 floats can differ by tiny fractions — exact '=' on monetary fields
# silently misses valid matches like 1500.10 stored as 1500.0999999...
AMOUNT_TOLERANCE = 0.001
MONETARY_PRECISION = 2


def _amounts_match(a, b):
    """Safe monetary comparison using Odoo's float_compare."""
    return float_compare(a, b, precision_digits=MONETARY_PRECISION) == 0


def _extract_ref_tokens(text):
    """
    Extract meaningful reference tokens from a payment_ref string.

    The Akahu sync engine builds payment_ref as:
        "description | particulars | code | reference"
    e.g. "Monthly invoice | INV/26-27/0013 | 4412 | Services"

    Splits on delimiters, uppercases, strips noise words, and returns a set
    of tokens matchable against account.move.name / payment_reference / ref.

    Examples:
        "Payment INV/26-27/0013"         → {'INV/26-27/0013'}
        "Rent | REF-0042 | monthly"      → {'REF-0042'}
        "Acme Ltd | INV-99 | consulting" → {'INV-99'}
    """
    if not text:
        return set()

    NOISE = {
        'PAYMENT', 'PAY', 'PAID', 'THE', 'FOR', 'AND', 'FROM', 'TO', 'OF',
        'A', 'AN', 'IN', 'ON', 'AT', 'BY', 'NZ', 'GST', 'INC', 'LIMITED',
        'LTD', 'TRANSFER', 'AKAHU', 'BANK', 'DIRECT', 'DEBIT', 'CREDIT',
        'INTERNET', 'BANKING', 'ONLINE', 'REF', 'REFERENCE', 'INVOICE',
        'SERVICES', 'SERVICE', 'MONTHLY', 'WEEKLY', 'ANNUAL',
    }

    tokens = set()
    for part in re.split(r'[|\s,;]+', text.upper()):
        part = part.strip()
        if not part or part in NOISE:
            continue
        if '/' in part:                             # INV/26-27/0013 style
            tokens.add(part)
        elif re.match(r'^[A-Z]+-\d+', part):       # REF-0042, PO-881 style
            tokens.add(part)
        elif re.match(r'^\d{4,}$', part):          # bare numeric codes >= 4 digits
            tokens.add(part)
        elif re.match(r'^(INV|BILL|PO|SO|RFQ|ORD|WO|JO|DO|RCPT)\d*', part):
            tokens.add(part)                        # known NZ doc-type prefixes
    return tokens


class AutoReconciliationEngine(models.Model):
    _name = 'auto.reconciliation.engine'
    _description = 'Auto Reconciliation Engine'

    @api.model
    def run_all(self, company_ids=None, journal_ids=None, preview_mode=False, triggered_by='manual'):
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        """
        Run all enabled reconciliation passes.

        :param company_ids: list of res.company IDs to process (None = all companies)
        :param journal_ids: list of account.journal IDs to restrict bank-statement
                            reconciliation to (None = all journals in the company).
                            Used by action_fetch_akahu_transactions to avoid running
                            a company-wide reconciliation when only one journal changed.
        :param preview_mode: if True, collect matches but do not apply them
        :param triggered_by: 'manual' or 'cron' (written to the audit log)
        """
        if not company_ids:
            # sudo(): res.company requires elevated read for multi-company enumeration in cron context
            companies = self.env['res.company'].sudo().search([])
        else:
            # sudo(): see above — same privilege rationale for browse path
            companies = self.env['res.company'].sudo().browse(company_ids)

        all_results = {}
        for company in companies:
            _logger.info("Auto Reconciliation: Processing company %s", company.name)
            try:
                results = self._process_company(
                    company,
                    preview_mode=preview_mode,
                    journal_ids=journal_ids,
                )
                all_results[company.id] = results
            except Exception as e:
                _logger.error("Auto Reconciliation failed for %s: %s", company.name, str(e))
                all_results[company.id] = {'error': str(e)}

        if not preview_mode:
            self._create_log_entries(all_results, triggered_by=triggered_by)
        return all_results

    def _process_company(self, company, preview_mode=False, journal_ids=None):
        # sudo(): cron technical user has read-only group; sudo() needed to read config written by managers
        config = self.env['auto.reconciliation.config'].sudo().search([
            ('company_id', '=', company.id), ('active', '=', True),
        ], limit=1)
        def run(fn, flag, **kw):
            if config and not getattr(config, flag):
                return {'matched': [], 'matched_count': 0}
            return fn(company, preview_mode, config=config, **kw)
        return {
            'company_name': company.name,
            'company_id': company.id,
            # journal_ids only applies to bank statement reconciliation — customer/vendor
            # payments and intercompany are not journal-scoped in the same way.
            'bank_statement':   run(self._reconcile_bank_statements,  'enable_bank',  journal_ids=journal_ids),
            'customer_payment': run(self._reconcile_customer_payments, 'enable_customer'),
            'vendor_payment':   run(self._reconcile_vendor_payments,   'enable_vendor'),
            'intercompany':     run(self._reconcile_intercompany,      'enable_intercompany'),
        }

    # ── BANK STATEMENTS ───────────────────────────────────────────────────────
    def _reconcile_bank_statements(self, company, preview_mode=False, config=None, journal_ids=None):
        match_by_partner   = not config or config.match_by_partner
        match_by_currency  = not config or config.match_by_currency
        match_by_amount    = not config or config.match_by_amount
        match_by_reference = not config or config.match_by_reference
        match_by_date_window = not config or config.match_by_date_window
        date_window_days   = (config.date_window_days if config else 60) or 60

        matched = []
        unmatched_count = 0
        # sudo(): cron technical user cannot read statement lines directly; escalate for reconciliation reads
        BankLine = self.env['account.bank.statement.line'].sudo()
        # sudo(): move lines are restricted; cron needs cross-company read for reconciliation matching
        MoveLine = self.env['account.move.line'].sudo()

        stmt_domain = [
            ('company_id', '=', company.id),
            ('is_reconciled', '=', False),
            ('journal_id.type', 'in', ['bank', 'cash']),
        ]
        if journal_ids:
            stmt_domain.append(('journal_id', 'in', journal_ids))

        stmt_lines = BankLine.search(stmt_domain)

        for stmt_line in stmt_lines:
            company_currency = company.currency_id
            stmt_currency = stmt_line.foreign_currency_id or stmt_line.currency_id or company_currency
            is_foreign = stmt_currency != company_currency
            match_amount = abs(stmt_line.amount_currency if is_foreign else stmt_line.amount)
            if match_amount == 0:
                continue

            # ── PASS 1: Reference-first lookup ────────────────────────────────
            # Try to find an invoice whose number / payment_reference / ref
            # appears in the bank transaction's payment_ref.
            # This is the primary matching strategy — your customers are asked
            # to quote the invoice number (e.g. INV/26-27/0013) when paying,
            # so this resolves same-amount duplicates precisely.
            best_candidate = None
            match_criteria = []

            if match_by_reference:
                ref_tokens = _extract_ref_tokens(stmt_line.payment_ref or '')
                if ref_tokens:
                    # Search invoices/bills whose name OR ref OR payment_reference
                    # contains any of the tokens extracted from the bank line.
                    # We use OR logic across fields but require at least one token hit.
                    ref_candidates = MoveLine.search([
                        ('company_id', '=', company.id),
                        ('reconciled', '=', False),
                        ('parent_state', '=', 'posted'),
                        ('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']),
                        ('account_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
                        '|', '|',
                        ('move_id.name', 'in', list(ref_tokens)),
                        ('move_id.payment_reference', 'in', list(ref_tokens)),
                        ('move_id.ref', 'in', list(ref_tokens)),
                    ], order='date asc, id asc', limit=20)

                    # Among reference hits, confirm amount also matches
                    for cand in ref_candidates:
                        if match_by_amount:
                            if is_foreign:
                                if not _amounts_match(abs(cand.amount_currency), match_amount):
                                    continue
                            else:
                                cand_amt = cand.debit if stmt_line.amount > 0 else cand.credit
                                if not _amounts_match(cand_amt, match_amount):
                                    continue
                        best_candidate = cand
                        match_criteria.append('reference')
                        if match_by_amount:
                            match_criteria.append('amount')
                        break  # first reference+amount hit wins

            # ── PASS 2: Amount + partner fallback ─────────────────────────────
            # Used when no payment reference was found in the bank transaction
            # (e.g. customer paid via internet banking without quoting the invoice).
            if not best_candidate:
                domain = [
                    ('company_id', '=', company.id),
                    ('reconciled', '=', False),
                    ('parent_state', '=', 'posted'),
                    ('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']),
                    ('account_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
                ]
                if match_by_currency:
                    domain.append(('currency_id', '=', stmt_currency.id))
                if match_by_partner and stmt_line.partner_id:
                    domain.append(('partner_id', '=', stmt_line.partner_id.id))
                if match_by_amount:
                    if is_foreign:
                        sign = 1 if stmt_line.amount >= 0 else -1
                        signed = sign * match_amount
                        domain += [
                            ('currency_id', '=', stmt_currency.id),
                            ('amount_currency', '>=', signed - AMOUNT_TOLERANCE),
                            ('amount_currency', '<=', signed + AMOUNT_TOLERANCE),
                        ]
                    else:
                        if stmt_line.amount > 0:
                            domain += [
                                ('debit', '>=', match_amount - AMOUNT_TOLERANCE),
                                ('debit', '<=', match_amount + AMOUNT_TOLERANCE),
                            ]
                        else:
                            domain += [
                                ('credit', '>=', match_amount - AMOUNT_TOLERANCE),
                                ('credit', '<=', match_amount + AMOUNT_TOLERANCE),
                            ]

                candidates = MoveLine.search(domain, limit=10, order='date asc, id asc')

                # Apply date window filter and float_compare confirmation
                for cand in candidates:
                    # Date window guard
                    if match_by_date_window and cand.date and stmt_line.date:
                        delta = abs((stmt_line.date - cand.date).days)
                        if delta > date_window_days:
                            continue  # skip — too old/future for this payment

                    # Float-compare confirmation
                    if match_by_amount:
                        if is_foreign:
                            if not _amounts_match(abs(cand.amount_currency), match_amount):
                                continue
                        else:
                            cand_amt = cand.debit if stmt_line.amount > 0 else cand.credit
                            if not _amounts_match(cand_amt, match_amount):
                                continue

                    best_candidate = cand
                    if match_by_amount:
                        match_criteria.append('amount')
                    if match_by_partner and stmt_line.partner_id:
                        match_criteria.append('partner')
                    if match_by_date_window:
                        match_criteria.append('date_window')
                    break

            # ── Accept or skip ────────────────────────────────────────────────
            if best_candidate:
                matched.append({
                    'type': 'bank_statement',
                    'statement_line_id': stmt_line.id,
                    'statement_line_name': stmt_line.payment_ref or stmt_line.name,
                    'move_line_id': best_candidate.id,
                    'move_line_name': best_candidate.name,
                    'amount': match_amount,
                    'currency': stmt_currency.name,
                    'date': str(stmt_line.date),
                    'company': company.name,
                    'match_criteria': ', '.join(match_criteria),
                })
                if not preview_mode:
                    self._apply_bank_reconciliation_community(stmt_line, best_candidate)
            else:
                unmatched_count += 1

        return {'matched': matched, 'matched_count': len(matched), 'unmatched_count': unmatched_count}

    def _apply_bank_reconciliation_community(self, stmt_line, move_line):
        """
        CRITICAL FIX 2: Correct suspense account fallback.

        Original bug: fallback used `l.id != move_line.id` to exclude the
        external move line. But move_line is on a different account.move
        entirely — its id never appears in stmt_line.move_id.line_ids, so
        the condition was always True and grabbed any unreconciled line
        (including the bank account line itself), corrupting journal entries.

        Fix: target the journal's suspense_account_id explicitly.
        """
        try:
            # Primary: receivable/payable line on the statement move
            stmt_move_lines = stmt_line.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in (
                    'asset_receivable', 'liability_payable'
                ) and not l.reconciled
            )
            if stmt_move_lines:
                (stmt_move_lines[0] | move_line).reconcile()
                return

            # CRITICAL FIX 2: Use journal's configured suspense account
            suspense_account = stmt_line.journal_id.suspense_account_id
            if suspense_account:
                suspense_lines = stmt_line.move_id.line_ids.filtered(
                    lambda l: l.account_id.id == suspense_account.id and not l.reconciled
                )
                if suspense_lines:
                    (suspense_lines[0] | move_line).reconcile()
                    return

            # Last resort: current asset/liability line
            fallback = stmt_line.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in (
                    'asset_current', 'liability_current'
                ) and not l.reconciled
            )
            if fallback:
                (fallback[0] | move_line).reconcile()
            else:
                _logger.warning(
                    "Bank recon: no suitable line on stmt_line %s to reconcile against move_line %s",
                    stmt_line.id, move_line.id
                )
        except Exception as e:
            _logger.warning("Bank recon failed for stmt_line %s: %s", stmt_line.id, str(e))

    # ── CUSTOMER PAYMENTS ─────────────────────────────────────────────────────
    def _reconcile_customer_payments(self, company, preview_mode=False, config=None):
        match_by_partner   = not config or config.match_by_partner
        match_by_currency  = not config or config.match_by_currency
        match_by_amount    = not config or config.match_by_amount
        match_by_reference = not config or config.match_by_reference
        matched = []
        # sudo(): cron technical user needs payment read for customer/vendor matching steps
        Payment = self.env['account.payment'].sudo()
        # sudo(): cron needs journal entry read/write for reconciliation; sudo() scoped to this method
        Move = self.env['account.move'].sudo()

        for payment in Payment.search([
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('payment_type', '=', 'inbound'), ('reconciled_invoice_ids', '=', False),
        ]):
            amt = float_round(payment.amount, precision_digits=MONETARY_PRECISION)
            invoice = None

            # ── Pass 1: match on payment memo/reference → invoice number ──────
            # In Odoo 18 Community, account.payment uses 'ref' as the memo /
            # communication field. There is no 'memo' field — using it raises
            # AttributeError and silently skips reference matching entirely.
            if match_by_reference:
                ref_tokens = _extract_ref_tokens(payment.ref or '')
                if ref_tokens:
                    ref_domain = [
                        ('company_id', '=', company.id),
                        ('move_type', '=', 'out_invoice'),
                        ('state', '=', 'posted'),
                        ('payment_state', 'in', ['not_paid', 'partial']),
                        '|', '|',
                        ('name', 'in', list(ref_tokens)),
                        ('payment_reference', 'in', list(ref_tokens)),
                        ('ref', 'in', list(ref_tokens)),
                    ]
                    if match_by_currency:
                        ref_domain.append(('currency_id', '=', payment.currency_id.id))
                    if match_by_partner and payment.partner_id:
                        ref_domain.append(('partner_id', '=', payment.partner_id.id))
                    ref_hits = Move.search(ref_domain, limit=5, order='invoice_date asc, id asc')
                    # Among reference hits confirm amount
                    for hit in ref_hits:
                        if match_by_amount and not _amounts_match(hit.amount_residual, amt):
                            continue
                        invoice = hit
                        break

            # ── Pass 2: amount + partner fallback ─────────────────────────────
            if not invoice:
                inv_domain = [
                    ('company_id', '=', company.id), ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']),
                ]
                if match_by_amount:
                    inv_domain += [
                        ('amount_residual', '>=', amt - AMOUNT_TOLERANCE),
                        ('amount_residual', '<=', amt + AMOUNT_TOLERANCE),
                    ]
                if match_by_currency:
                    inv_domain.append(('currency_id', '=', payment.currency_id.id))
                if match_by_partner and payment.partner_id:
                    inv_domain.append(('partner_id', '=', payment.partner_id.id))
                candidates = Move.search(inv_domain, limit=1, order='invoice_date asc, id asc')
                if match_by_amount and candidates and not _amounts_match(candidates[0].amount_residual, amt):
                    candidates = candidates.browse([])
                if candidates:
                    invoice = candidates[0]

            if invoice:
                matched.append({
                    'type': 'customer_payment', 'payment_id': payment.id,
                    'payment_name': payment.name, 'invoice_id': invoice.id,
                    'invoice_name': invoice.name, 'amount': payment.amount,
                    'currency': payment.currency_id.name,
                    'partner': payment.partner_id.name if payment.partner_id else '',
                    'company': company.name,
                    'match_criteria': 'reference, amount' if (match_by_reference and payment.ref) else 'amount, partner',
                })
                if not preview_mode:
                    self._apply_ar_reconciliation(payment, invoice, 'asset_receivable')
        return {'matched': matched, 'matched_count': len(matched)}

    # ── VENDOR PAYMENTS ───────────────────────────────────────────────────────
    def _reconcile_vendor_payments(self, company, preview_mode=False, config=None):
        match_by_partner   = not config or config.match_by_partner
        match_by_currency  = not config or config.match_by_currency
        match_by_amount    = not config or config.match_by_amount
        match_by_reference = not config or config.match_by_reference
        matched = []
        Payment = self.env['account.payment'].sudo()
        Move = self.env['account.move'].sudo()

        for payment in Payment.search([
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('payment_type', '=', 'outbound'), ('reconciled_bill_ids', '=', False),
            ('journal_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
        ]):
            amt = float_round(payment.amount, precision_digits=MONETARY_PRECISION)
            bill = None

            # ── Pass 1: match on payment ref → bill number ────────────────────
            if match_by_reference:
                ref_tokens = _extract_ref_tokens(payment.ref or '')
                if ref_tokens:
                    ref_domain = [
                        ('company_id', '=', company.id),
                        ('move_type', '=', 'in_invoice'),
                        ('state', '=', 'posted'),
                        ('payment_state', 'in', ['not_paid', 'partial']),
                        '|', '|',
                        ('name', 'in', list(ref_tokens)),
                        ('payment_reference', 'in', list(ref_tokens)),
                        ('ref', 'in', list(ref_tokens)),
                    ]
                    if match_by_currency:
                        ref_domain.append(('currency_id', '=', payment.currency_id.id))
                    if match_by_partner and payment.partner_id:
                        ref_domain.append(('partner_id', '=', payment.partner_id.id))
                    ref_hits = Move.search(ref_domain, limit=5, order='invoice_date asc, id asc')
                    for hit in ref_hits:
                        if match_by_amount and not _amounts_match(hit.amount_residual, amt):
                            continue
                        bill = hit
                        break

            # ── Pass 2: amount + partner fallback ─────────────────────────────
            if not bill:
                bill_domain = [
                    ('company_id', '=', company.id), ('move_type', '=', 'in_invoice'),
                    ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']),
                ]
                if match_by_amount:
                    bill_domain += [
                        ('amount_residual', '>=', amt - AMOUNT_TOLERANCE),
                        ('amount_residual', '<=', amt + AMOUNT_TOLERANCE),
                    ]
                if match_by_currency:
                    bill_domain.append(('currency_id', '=', payment.currency_id.id))
                if match_by_partner and payment.partner_id:
                    bill_domain.append(('partner_id', '=', payment.partner_id.id))
                candidates = Move.search(bill_domain, limit=1, order='invoice_date asc, id asc')
                if match_by_amount and candidates and not _amounts_match(candidates[0].amount_residual, amt):
                    candidates = candidates.browse([])
                if candidates:
                    bill = candidates[0]

            if bill:
                matched.append({
                    'type': 'vendor_payment', 'payment_id': payment.id,
                    'payment_name': payment.name, 'bill_id': bill.id,
                    'bill_name': bill.name, 'amount': payment.amount,
                    'currency': payment.currency_id.name,
                    'partner': payment.partner_id.name if payment.partner_id else '',
                    'company': company.name,
                    'match_criteria': 'reference, amount' if (match_by_reference and payment.ref) else 'amount, partner',
                })
                if not preview_mode:
                    self._apply_ar_reconciliation(payment, bill, 'liability_payable')
        return {'matched': matched, 'matched_count': len(matched)}

    def _apply_ar_reconciliation(self, payment, move, account_type):
        try:
            p_lines = payment.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type == account_type and not l.reconciled
            )
            m_lines = move.line_ids.filtered(
                lambda l: l.account_id.account_type == account_type and not l.reconciled
            )
            if p_lines and m_lines:
                (p_lines[0] | m_lines[0]).reconcile()
        except Exception as e:
            _logger.warning("AR reconciliation failed for payment %s: %s", payment.id, str(e))

    # ── INTER-COMPANY ─────────────────────────────────────────────────────────
    def _reconcile_intercompany(self, company, preview_mode=False, config=None):
        matched = []
        MoveLine = self.env['account.move.line'].sudo()

        # sudo(): cron technical user needs cross-company mapping read for inter-company reconciliation
        mappings = self.env['akahu.company.mapping'].sudo().search([
            ('company_id', '=', company.id), ('active', '=', True),
        ])
        if not mappings:
            return {'matched': [], 'matched_count': 0}

        partner_to_company = {m.partner_id.id: m.counterpart_company_id.id for m in mappings}

        ic_lines = MoveLine.search([
            ('company_id', '=', company.id), ('reconciled', '=', False),
            ('parent_state', '=', 'posted'),
            ('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']),
            ('account_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
            ('partner_id', 'in', list(partner_to_company.keys())),
        ])

        for line in ic_lines:
            cc_id = partner_to_company.get(line.partner_id.id)
            if not cc_id:
                continue

            domain = [
                ('company_id', '=', cc_id), ('reconciled', '=', False),
                ('parent_state', '=', 'posted'),
                ('account_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
            ]
            # CRITICAL FIX 1: Tolerance range for IC matching
            if line.currency_id and line.currency_id != company.currency_id:
                target = -line.amount_currency
                domain += [
                    ('currency_id', '=', line.currency_id.id),
                    ('amount_currency', '>=', target - AMOUNT_TOLERANCE),
                    ('amount_currency', '<=', target + AMOUNT_TOLERANCE),
                    ('account_id.account_type', '=',
                     'liability_payable' if line.debit > 0 else 'asset_receivable'),
                ]
            else:
                if line.debit > 0:
                    domain += [
                        ('credit', '>=', line.debit - AMOUNT_TOLERANCE),
                        ('credit', '<=', line.debit + AMOUNT_TOLERANCE),
                        ('account_id.account_type', '=', 'liability_payable'),
                    ]
                else:
                    domain += [
                        ('debit', '>=', line.credit - AMOUNT_TOLERANCE),
                        ('debit', '<=', line.credit + AMOUNT_TOLERANCE),
                        ('account_id.account_type', '=', 'asset_receivable'),
                    ]

            # H1 FIX: deterministic ordering — oldest matching entry preferred.
            counterpart = MoveLine.search(domain, limit=1, order='date asc, id asc')
            if counterpart:
                cc_name = self.env['res.company'].browse(cc_id).name
                line_currency = line.currency_id or company.currency_id
                matched.append({
                    'type': 'intercompany', 'line_id': line.id, 'line_name': line.name,
                    'counterpart_line_id': counterpart.id,
                    'counterpart_line_name': counterpart.name,
                    'amount': abs(line.amount_currency if line.currency_id else (line.debit or line.credit)),
                    'currency': line_currency.name,
                    'company_from': company.name, 'company_to': cc_name,
                })
                if not preview_mode:
                    try:
                        # BUG FIX 5: Combining records from two different company
                        # environments with `|` keeps each record in its own env,
                        # so Odoo's multi-company record rules block the reconcile()
                        # call and it silently fails.  Re-fetching both IDs through
                        # a single sudo() env ensures they share the same environment
                        # and bypasses the cross-company rule restriction.
                        # sudo(): targeted browse to reconcile specific move lines identified earlier in this method
                        self.env['account.move.line'].sudo().browse(
                            [line.id, counterpart.id]
                        ).reconcile()
                    except Exception as e:
                        _logger.warning("IC reconciliation failed: %s", str(e))

        return {'matched': matched, 'matched_count': len(matched)}

    # ── LOGGING ───────────────────────────────────────────────────────────────
    def _create_log_entries(self, all_results, triggered_by='manual'):
        # sudo(): cron technical user has no create permission on auto.reconciliation.log
        Log = self.env['auto.reconciliation.log'].sudo()
        for company_id, result in all_results.items():
            if 'error' in result:
                Log.create({
                    'company_id': company_id, 'state': 'failed',
                    'notes': result['error'], 'total_matched': 0,
                    'triggered_by': triggered_by,
                })
                continue
            total = sum(
                result.get(k, {}).get('matched_count', 0)
                for k in ['bank_statement', 'customer_payment', 'vendor_payment', 'intercompany']
            )
            Log.create({
                'company_id': company_id,
                'bank_matched': result.get('bank_statement', {}).get('matched_count', 0),
                'customer_matched': result.get('customer_payment', {}).get('matched_count', 0),
                'vendor_matched': result.get('vendor_payment', {}).get('matched_count', 0),
                'intercompany_matched': result.get('intercompany', {}).get('matched_count', 0),
                'total_matched': total, 'state': 'done',
                'triggered_by': triggered_by,
            })

    @api.model
    def cron_run_auto_reconciliation(self):
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        _logger.info("Auto Reconciliation Cron: Starting")
        self.run_all(triggered_by='cron')
        _logger.info("Auto Reconciliation Cron: Completed")
