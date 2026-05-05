# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

_logger = logging.getLogger(__name__)

PAYROLL_ACCOUNT_CODES = ['820', '825', '830', '835', '840', '9500', '9510', '9520']

# CRITICAL FIX 1: Monetary tolerance for float-safe comparisons.
# IEEE 754 floats can differ by tiny fractions — exact '=' matching silently
# misses valid amounts like 1500.10 stored as 1500.0999999...
AMOUNT_TOLERANCE = 0.001
MONETARY_PRECISION = 2


def _amounts_match(a, b):
    """Safe monetary comparison using Odoo's float_compare."""
    return float_compare(a, b, precision_digits=MONETARY_PRECISION) == 0


class AutoReconciliationEngine(models.Model):
    _name = 'auto.reconciliation.engine'
    _description = 'Auto Reconciliation Engine'

    @api.model
    def run_all(self, company_ids=None, preview_mode=False, triggered_by='manual'):
        if not company_ids:
            companies = self.env['res.company'].sudo().search([])
        else:
            companies = self.env['res.company'].sudo().browse(company_ids)

        all_results = {}
        for company in companies:
            _logger.info("Auto Reconciliation: Processing company %s", company.name)
            try:
                results = self._process_company(company, preview_mode=preview_mode)
                all_results[company.id] = results
            except Exception as e:
                _logger.error("Auto Reconciliation failed for %s: %s", company.name, str(e))
                all_results[company.id] = {'error': str(e)}

        if not preview_mode:
            self._create_log_entries(all_results, triggered_by=triggered_by)
        return all_results

    def _process_company(self, company, preview_mode=False):
        config = self.env['auto.reconciliation.config'].sudo().search([
            ('company_id', '=', company.id), ('active', '=', True),
        ], limit=1)
        run = lambda fn, flag: fn(company, preview_mode) if (not config or getattr(config, flag)) else {'matched': [], 'matched_count': 0}
        return {
            'company_name': company.name,
            'company_id': company.id,
            'bank_statement':   run(self._reconcile_bank_statements,  'enable_bank'),
            'customer_payment': run(self._reconcile_customer_payments, 'enable_customer'),
            'vendor_payment':   run(self._reconcile_vendor_payments,   'enable_vendor'),
            'intercompany':     run(self._reconcile_intercompany,      'enable_intercompany'),
        }

    # ── BANK STATEMENTS ───────────────────────────────────────────────────────
    def _reconcile_bank_statements(self, company, preview_mode=False):
        matched = []
        unmatched_count = 0
        BankLine = self.env['account.bank.statement.line'].sudo()
        MoveLine = self.env['account.move.line'].sudo()

        stmt_lines = BankLine.search([
            ('company_id', '=', company.id),
            ('is_reconciled', '=', False),
            ('journal_id.type', 'in', ['bank', 'cash']),
        ])

        for stmt_line in stmt_lines:
            company_currency = company.currency_id
            stmt_currency = stmt_line.foreign_currency_id or stmt_line.currency_id or company_currency
            is_foreign = stmt_currency != company_currency
            match_amount = abs(stmt_line.amount_currency if is_foreign else stmt_line.amount)
            if match_amount == 0:
                continue

            domain = [
                ('company_id', '=', company.id),
                ('reconciled', '=', False),
                ('parent_state', '=', 'posted'),
                ('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']),
                ('account_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
            ]

            # CRITICAL FIX 1: Use tolerance range instead of exact float equality.
            # ('debit', '=', amount) silently fails when IEEE 754 rounding causes
            # tiny differences between stored floats.
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

            candidates = MoveLine.search(domain, limit=1)

            # Secondary guard: confirm with float_compare before accepting
            if candidates:
                cand = candidates[0]
                if is_foreign:
                    confirmed = _amounts_match(abs(cand.amount_currency), match_amount)
                else:
                    confirmed = _amounts_match(
                        cand.debit if stmt_line.amount > 0 else cand.credit,
                        match_amount
                    )
                if not confirmed:
                    candidates = candidates.browse([])

            if candidates:
                matched.append({
                    'type': 'bank_statement',
                    'statement_line_id': stmt_line.id,
                    'statement_line_name': stmt_line.payment_ref or stmt_line.name,
                    'move_line_id': candidates[0].id,
                    'move_line_name': candidates[0].name,
                    'amount': match_amount,
                    'currency': stmt_currency.name,
                    'date': str(stmt_line.date),
                    'company': company.name,
                })
                if not preview_mode:
                    self._apply_bank_reconciliation_community(stmt_line, candidates[0])
            else:
                unmatched_count += 1

        return {'matched': matched, 'matched_count': len(matched), 'unmatched_count': unmatched_count}

    def _apply_bank_reconciliation_community(self, stmt_line, move_line):
        """
        Community-compatible reconciliation via move_line.reconcile().

        CRITICAL FIX 2: Original fallback used `l.id != move_line.id` to exclude
        the external move line from the statement's own lines. But move_line lives
        on a different account.move entirely — its id will never appear in
        stmt_line.move_id.line_ids, so the condition was always True and the fallback
        grabbed any unreconciled line (including the bank account line itself),
        risking corrupt journal entries.

        Correct approach:
          1. Primary: find receivable/payable lines on the statement move.
          2. Fallback: target the journal's suspense_account_id specifically.
          3. Last resort: any current asset/liability line (non-standard setups).
        """
        try:
            # Primary: statement move has a receivable/payable line
            stmt_move_lines = stmt_line.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in (
                    'asset_receivable', 'liability_payable'
                ) and not l.reconciled
            )
            if stmt_move_lines:
                (stmt_move_lines[0] | move_line).reconcile()
                return

            # CRITICAL FIX 2: Correct suspense fallback — use the journal's
            # configured suspense account, not just "any unreconciled line
            # that isn't move_line" (which was always True and grabbed wrong lines).
            suspense_account = stmt_line.journal_id.suspense_account_id
            if suspense_account:
                suspense_lines = stmt_line.move_id.line_ids.filtered(
                    lambda l: l.account_id.id == suspense_account.id and not l.reconciled
                )
                if suspense_lines:
                    (suspense_lines[0] | move_line).reconcile()
                    return

            # Last resort: any current asset/liability line (non-standard setups)
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
            _logger.warning("Bank recon (Community) failed for stmt_line %s: %s", stmt_line.id, str(e))

    # ── CUSTOMER PAYMENTS ─────────────────────────────────────────────────────
    def _reconcile_customer_payments(self, company, preview_mode=False):
        matched = []
        Payment = self.env['account.payment'].sudo()
        Move = self.env['account.move'].sudo()

        for payment in Payment.search([
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('payment_type', '=', 'inbound'), ('reconciled_invoice_ids', '=', False),
        ]):
            # CRITICAL FIX 1: Tolerance range instead of exact float equality.
            amt = float_round(payment.amount, precision_digits=MONETARY_PRECISION)
            invoices = Move.search([
                ('company_id', '=', company.id), ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']),
                ('amount_residual', '>=', amt - AMOUNT_TOLERANCE),
                ('amount_residual', '<=', amt + AMOUNT_TOLERANCE),
                ('currency_id', '=', payment.currency_id.id),
                ('partner_id', '=', payment.partner_id.id),
            ], limit=1)
            # Secondary guard
            if invoices and not _amounts_match(invoices[0].amount_residual, amt):
                invoices = invoices.browse([])

            if invoices:
                matched.append({
                    'type': 'customer_payment', 'payment_id': payment.id,
                    'payment_name': payment.name, 'invoice_id': invoices[0].id,
                    'invoice_name': invoices[0].name, 'amount': payment.amount,
                    'currency': payment.currency_id.name,
                    'partner': payment.partner_id.name, 'company': company.name,
                })
                if not preview_mode:
                    self._apply_ar_reconciliation(payment, invoices[0], 'asset_receivable')
        return {'matched': matched, 'matched_count': len(matched)}

    # ── VENDOR PAYMENTS ───────────────────────────────────────────────────────
    def _reconcile_vendor_payments(self, company, preview_mode=False):
        matched = []
        Payment = self.env['account.payment'].sudo()
        Move = self.env['account.move'].sudo()

        for payment in Payment.search([
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('payment_type', '=', 'outbound'), ('reconciled_bill_ids', '=', False),
            ('journal_id.name', 'not ilike', 'payroll'),
        ]):
            # CRITICAL FIX 1: Tolerance range instead of exact float equality.
            amt = float_round(payment.amount, precision_digits=MONETARY_PRECISION)
            bills = Move.search([
                ('company_id', '=', company.id), ('move_type', '=', 'in_invoice'),
                ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']),
                ('amount_residual', '>=', amt - AMOUNT_TOLERANCE),
                ('amount_residual', '<=', amt + AMOUNT_TOLERANCE),
                ('currency_id', '=', payment.currency_id.id),
                ('partner_id', '=', payment.partner_id.id),
                ('invoice_line_ids.account_id.code', 'not in', PAYROLL_ACCOUNT_CODES),
            ], limit=1)
            # Secondary guard
            if bills and not _amounts_match(bills[0].amount_residual, amt):
                bills = bills.browse([])

            if bills:
                matched.append({
                    'type': 'vendor_payment', 'payment_id': payment.id,
                    'payment_name': payment.name, 'bill_id': bills[0].id,
                    'bill_name': bills[0].name, 'amount': payment.amount,
                    'currency': payment.currency_id.name,
                    'partner': payment.partner_id.name, 'company': company.name,
                })
                if not preview_mode:
                    self._apply_ar_reconciliation(payment, bills[0], 'liability_payable')
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
            _logger.warning("Payment/invoice reconciliation failed for payment %s: %s", payment.id, str(e))

    # ── INTER-COMPANY ─────────────────────────────────────────────────────────
    def _reconcile_intercompany(self, company, preview_mode=False):
        matched = []
        MoveLine = self.env['account.move.line'].sudo()

        mappings = self.env['akahu.company.mapping'].sudo().search([
            ('company_id', '=', company.id), ('active', '=', True),
        ])
        if not mappings:
            _logger.info("IC reconciliation skipped for %s: no mappings set up.", company.name)
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
            # CRITICAL FIX 1: Tolerance range for IC matching too
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

            counterpart = MoveLine.search(domain, limit=1)
            if counterpart:
                cc_name = self.env['res.company'].browse(cc_id).name
                line_currency = line.currency_id or company.currency_id
                matched.append({
                    'type': 'intercompany', 'line_id': line.id, 'line_name': line.name,
                    'counterpart_line_id': counterpart.id, 'counterpart_line_name': counterpart.name,
                    'amount': abs(line.amount_currency if line.currency_id else (line.debit or line.credit)),
                    'currency': line_currency.name,
                    'company_from': company.name, 'company_to': cc_name,
                })
                if not preview_mode:
                    try:
                        (line | counterpart).reconcile()
                    except Exception as e:
                        _logger.warning("IC reconciliation failed: %s", str(e))

        return {'matched': matched, 'matched_count': len(matched)}

    # ── LOGGING ───────────────────────────────────────────────────────────────
    def _create_log_entries(self, all_results, triggered_by='manual'):
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
        _logger.info("Auto Reconciliation Cron: Starting")
        self.run_all(triggered_by='cron')
        _logger.info("Auto Reconciliation Cron: Completed")
