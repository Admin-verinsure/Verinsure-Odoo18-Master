# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import json


class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'
    _description = 'Customer Statement Report Wizard'

    # ── Quick Date Range Preset ───────────────────────────────────
    date_range_preset = fields.Selection([
        ('custom',        'Custom Range'),
        ('this_month',    'This Month'),
        ('last_month',    'Last Month'),
        ('this_quarter',  'This Quarter'),
        ('last_quarter',  'Last Quarter'),
        ('this_year',     'This Financial Year'),
        ('last_year',     'Last Financial Year'),
        ('last_30',       'Last 30 Days'),
        ('last_60',       'Last 60 Days'),
        ('last_90',       'Last 90 Days'),
        ('last_180',      'Last 180 Days'),
    ], string='Period', default='this_month', required=True)

    # ── Date Range ────────────────────────────────────────────────
    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.today,
    )

    @api.onchange('date_range_preset')
    def _onchange_date_range_preset(self):
        today = date.today()
        preset = self.date_range_preset
        if preset == 'custom':
            return
        elif preset == 'this_month':
            self.date_from = today.replace(day=1)
            self.date_to = today.replace(day=1) + relativedelta(months=1) - timedelta(days=1)
        elif preset == 'last_month':
            first = today.replace(day=1) - relativedelta(months=1)
            self.date_from = first
            self.date_to = first + relativedelta(months=1) - timedelta(days=1)
        elif preset == 'this_quarter':
            q = (today.month - 1) // 3
            self.date_from = date(today.year, q * 3 + 1, 1)
            self.date_to = self.date_from + relativedelta(months=3) - timedelta(days=1)
        elif preset == 'last_quarter':
            q = (today.month - 1) // 3
            start = date(today.year, q * 3 + 1, 1) - relativedelta(months=3)
            self.date_from = start
            self.date_to = start + relativedelta(months=3) - timedelta(days=1)
        elif preset == 'this_year':
            self.date_from = date(today.year, 1, 1)
            self.date_to = date(today.year, 12, 31)
        elif preset == 'last_year':
            self.date_from = date(today.year - 1, 1, 1)
            self.date_to = date(today.year - 1, 12, 31)
        elif preset == 'last_30':
            self.date_from = today - timedelta(days=30)
            self.date_to = today
        elif preset == 'last_60':
            self.date_from = today - timedelta(days=60)
            self.date_to = today
        elif preset == 'last_90':
            self.date_from = today - timedelta(days=90)
            self.date_to = today
        elif preset == 'last_180':
            self.date_from = today - timedelta(days=180)
            self.date_to = today

    # ── Customer Selection ────────────────────────────────────────
    partner_ids = fields.Many2many(
        'res.partner',
        'customer_statement_partner_rel',
        'wizard_id', 'partner_id',
        string='Customers',
        domain="[('customer_rank', '>', 0)]",
    )

    # ── Filters ───────────────────────────────────────────────────
    journal_ids = fields.Many2many(
        'account.journal',
        'customer_statement_journal_rel',
        'wizard_id', 'journal_id',
        string='Journals',
        domain="[('type', 'in', ['sale', 'general', 'cash', 'bank'])]",
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    # ── Statement Options ─────────────────────────────────────────
    include_unreconciled = fields.Boolean(
        string='Include Unreconciled Only',
        default=False,
        help='Show only entries that are not fully reconciled',
    )
    show_aging = fields.Boolean(
        string='Show Aging Analysis',
        default=True,
    )
    show_opening_balance = fields.Boolean(
        string='Show Opening Balance',
        default=True,
    )
    group_by_currency = fields.Boolean(
        string='Group by Currency',
        default=False,
    )
    statement_type = fields.Selection([
        ('detailed', 'Detailed Statement'),
        ('summary', 'Summary Only'),
        ('outstanding', 'Outstanding Items Only'),
    ], string='Statement Type', default='detailed', required=True)

    # ── Aging Buckets ─────────────────────────────────────────────
    aging_bucket_1 = fields.Integer(string='Bucket 1 (days)', default=30)
    aging_bucket_2 = fields.Integer(string='Bucket 2 (days)', default=60)
    aging_bucket_3 = fields.Integer(string='Bucket 3 (days)', default=90)
    aging_bucket_4 = fields.Integer(string='Bucket 4 (days)', default=120)

    # ─────────────────────────────────────────────────────────────
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError(_("'Date From' must be earlier than 'Date To'."))

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.currency_id = self.company_id.currency_id

    # ── Core Data Computation ─────────────────────────────────────
    def _get_partners(self):
        if self.partner_ids:
            return self.partner_ids
        # If called from action menu with active records
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            return self.env['res.partner'].browse(active_ids)
        return self.env['res.partner'].search([
            ('customer_rank', '>', 0),
            ('company_id', 'in', [False, self.company_id.id]),
        ])

    def _get_opening_balance(self, partner):
        """Compute balance before date_from."""
        domain = [
            ('partner_id', '=', partner.id),
            ('account_id.account_type', 'in', ['asset_receivable']),
            ('company_id', '=', self.company_id.id),
            ('date', '<', self.date_from),
            ('move_id.state', '=', 'posted'),
        ]
        if self.currency_id != self.company_id.currency_id:
            domain.append(('currency_id', '=', self.currency_id.id))

        lines = self.env['account.move.line'].search(domain)
        if self.currency_id != self.company_id.currency_id:
            return sum(lines.mapped('amount_currency'))
        return sum(lines.mapped('balance'))

    def _get_move_lines(self, partner):
        """Get account move lines for the period."""
        domain = [
            ('partner_id', '=', partner.id),
            ('account_id.account_type', 'in', ['asset_receivable']),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('move_id.state', '=', 'posted'),
        ]
        if self.journal_ids:
            domain.append(('journal_id', 'in', self.journal_ids.ids))
        if self.currency_id != self.company_id.currency_id:
            domain.append(('currency_id', '=', self.currency_id.id))
        if self.include_unreconciled:
            domain.append(('reconciled', '=', False))

        lines = self.env['account.move.line'].search(domain, order='date asc, move_id asc')
        result = []
        running_balance = self._get_opening_balance(partner) if self.show_opening_balance else 0.0

        for line in lines:
            if self.currency_id != self.company_id.currency_id:
                debit = line.amount_currency if line.amount_currency > 0 else 0.0
                credit = -line.amount_currency if line.amount_currency < 0 else 0.0
            else:
                debit = line.debit
                credit = line.credit

            running_balance += debit - credit
            result.append({
                'date': line.date,
                'move_name': line.move_id.name,
                'ref': line.move_id.ref or '',
                'journal': line.journal_id.name,
                'label': line.name or line.move_id.name,
                'due_date': line.date_maturity or line.date,
                'debit': debit,
                'credit': credit,
                'balance': running_balance,
                'currency_symbol': self.currency_id.symbol,
                'reconciled': line.reconciled,
                'amount_residual': line.amount_residual if not self.currency_id != self.company_id.currency_id else line.amount_residual_currency,
                'move_type': line.move_id.move_type,
                'invoice_origin': line.move_id.invoice_origin or '',
            })
        return result

    def _get_aging_data(self, partner):
        """Compute aging buckets for outstanding receivables."""
        today = date.today()
        domain = [
            ('partner_id', '=', partner.id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('company_id', '=', self.company_id.id),
            ('reconciled', '=', False),
            ('move_id.state', '=', 'posted'),
            ('date_maturity', '<=', self.date_to),
        ]
        lines = self.env['account.move.line'].search(domain)

        b1, b2, b3, b4, b5 = 0.0, 0.0, 0.0, 0.0, 0.0
        for line in lines:
            due = line.date_maturity or line.date
            days_overdue = (today - due).days if isinstance(due, date) else 0
            residual = line.amount_residual if self.currency_id == self.company_id.currency_id else line.amount_residual_currency

            if days_overdue <= 0:
                b1 += residual
            elif days_overdue <= self.aging_bucket_1:
                b2 += residual
            elif days_overdue <= self.aging_bucket_2:
                b3 += residual
            elif days_overdue <= self.aging_bucket_3:
                b4 += residual
            else:
                b5 += residual

        return {
            'current': b1,
            'bucket_1': b2,
            'bucket_2': b3,
            'bucket_3': b4,
            'bucket_4_plus': b5,
            'total': b1 + b2 + b3 + b4 + b5,
        }

    def _get_statement_data(self):
        """Build the full data payload for the report."""
        partners = self._get_partners()
        statements = []

        for partner in partners:
            opening_balance = self._get_opening_balance(partner) if self.show_opening_balance else 0.0
            lines = self._get_move_lines(partner)
            aging = self._get_aging_data(partner) if self.show_aging else {}

            closing_balance = opening_balance
            if lines:
                closing_balance = lines[-1]['balance']
            else:
                closing_balance = opening_balance

            total_debit = sum(l['debit'] for l in lines)
            total_credit = sum(l['credit'] for l in lines)

            if self.statement_type == 'outstanding':
                lines = [l for l in lines if not l['reconciled']]

            statements.append({
                'partner': partner,
                'partner_name': partner.name,
                'partner_ref': partner.ref or '',
                'partner_street': partner.street or '',
                'partner_city': partner.city or '',
                'partner_country': partner.country_id.name if partner.country_id else '',
                'partner_vat': partner.vat or '',
                'partner_phone': partner.phone or '',
                'partner_email': partner.email or '',
                'opening_balance': opening_balance,
                'lines': lines,
                'closing_balance': closing_balance,
                'total_debit': total_debit,
                'total_credit': total_credit,
                'aging': aging,
                'currency': self.currency_id,
                'has_balance': abs(closing_balance) > 0.001,
            })

        # Filter out zero-balance partners for outstanding
        if self.statement_type == 'outstanding':
            statements = [s for s in statements if s['has_balance'] or s['lines']]

        return statements

    # ── Report Actions ────────────────────────────────────────────
    def action_print_pdf(self):
        """Generate PDF report."""
        self.ensure_one()
        data = {
            'wizard_id': self.id,
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'show_aging': self.show_aging,
            'show_opening_balance': self.show_opening_balance,
            'statement_type': self.statement_type,
            'aging_bucket_1': self.aging_bucket_1,
            'aging_bucket_2': self.aging_bucket_2,
            'aging_bucket_3': self.aging_bucket_3,
            'aging_bucket_4': self.aging_bucket_4,
        }
        return self.env.ref(
            'customer_statement_report.action_customer_statement_pdf'
        ).report_action(self, data=data)

    def action_preview(self):
        """Open HTML preview in browser."""
        self.ensure_one()
        return self.action_print_pdf()

    # ── Called by Report Template ─────────────────────────────────
    def get_report_data(self):
        """Public method called by QWeb report template."""
        self.ensure_one()
        return self._get_statement_data()
