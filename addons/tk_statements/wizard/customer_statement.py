# -*- coding: utf-8 -*-
from datetime import date
from odoo import fields, models, api
from odoo.exceptions import UserError


class CustomerStatementWizard(models.TransientModel):
    """
    Wizard for generating Customer Statement Reports.

    Columns: Date | Document No. | Type | Debit | Credit | Paid | Balance
    - Debit  : invoice amount_total
    - Credit : credit note amount_total
    - Paid   : inbound payment amount
    - Balance: running balance (opening + debits - credits - payments)
    """
    _name = 'customer.statement.wizard'
    _description = "Customer Statement Report"
    _rec_name = 'partner_id'

    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    end_date = fields.Date(
        string="End Date",
        required=True,
        default=fields.Date.today,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        required=True,
        domain=[('invoice_ids', '!=', False)],
    )
    include_zero_balance = fields.Boolean(
        string="Include Fully Paid",
        default=False,
        help="Include invoices and credit notes that are fully settled.",
    )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _check_dates(self):
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be later than End Date.")

    # ------------------------------------------------------------------
    # Core data builder — single source of truth used by PDF + Excel
    # ------------------------------------------------------------------

    def _get_statement_data(self):
        self.ensure_one()
        self._check_dates()

        domain_base = [
            ('partner_id', 'child_of', self.partner_id.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
        ]

        # ---- Opening balance: outstanding amount before start_date ----
        opening_moves = self.env['account.move'].search(
            domain_base + [('invoice_date', '<', self.start_date)],
            order='invoice_date asc, name asc',
        )
        opening_balance = 0.0
        for move in opening_moves:
            if move.move_type == 'out_invoice':
                opening_balance += move.amount_residual
            else:
                opening_balance -= move.amount_residual

        # ---- Period: invoices + credit notes ----
        period_moves = self.env['account.move'].search(
            domain_base + [
                ('invoice_date', '>=', self.start_date),
                ('invoice_date', '<=', self.end_date),
            ],
            order='invoice_date asc, name asc',
        )

        # ---- Period: inbound payments ----
        period_payments = self.env['account.payment'].search([
            ('partner_id', 'child_of', self.partner_id.id),
            ('payment_type', '=', 'inbound'),
            ('state', '=', 'posted'),
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date),
        ], order='date asc, name asc')

        # ---- Build raw line list ----
        raw_lines = []

        for move in period_moves:
            raw_lines.append({
                'date': move.invoice_date,
                'name': move.name,
                'move_type': move.move_type,
                'type_label': 'Invoice' if move.move_type == 'out_invoice' else 'Credit Note',
                'debit':   move.amount_total if move.move_type == 'out_invoice' else None,
                'credit':  move.amount_total if move.move_type == 'out_refund'  else None,
                'paid':    None,
                'residual': move.amount_residual,
            })

        for payment in period_payments:
            raw_lines.append({
                'date': payment.date,
                'name': payment.name,
                'move_type': 'payment',
                'type_label': 'Payment',
                'debit':   None,
                'credit':  None,
                'paid':    payment.amount,
                'residual': 0.0,
            })

        # Sort by date then document name
        raw_lines.sort(key=lambda l: (l['date'], l['name']))

        lines = []
        running = opening_balance
        for line in raw_lines:
            if line['debit']:
                running += line['debit']
            if line['credit']:
                running -= line['credit']
            if line['paid']:
                running -= line['paid']

            # Skip fully settled invoices/credit notes when flag is off
            if (not self.include_zero_balance
                    and line['move_type'] != 'payment'
                    and line['residual'] == 0):
                continue

            lines.append({
                'date':            line['date'],
                'name':            line['name'],
                'move_type':       line['move_type'],
                'type_label':      line['type_label'],
                'debit':           round(line['debit'],  2) if line['debit']  else None,
                'credit':          round(line['credit'], 2) if line['credit'] else None,
                'paid':            round(line['paid'],   2) if line['paid']   else None,
                'running_balance': round(running, 2),
            })

        # ---- Company ----
        company_rec = self.env.company
        addr_parts = filter(None, [
            company_rec.street, company_rec.street2,
            company_rec.city, company_rec.zip,
            company_rec.state_id.name  if company_rec.state_id  else None,
            company_rec.country_id.name if company_rec.country_id else None,
        ])
        company_info = {
            'name':            company_rec.name,
            'address':         ', '.join(addr_parts),
            'currency_symbol': company_rec.currency_id.symbol,
        }

        partner = self.partner_id

        return {
            'company':      company_rec,
            'company_info': company_info,
            'partner': {
                'name':    partner.name,
                'street':  partner.street  or '',
                'street2': partner.street2 or '',
                'city':    partner.city    or '',
                'zip':     partner.zip     or '',
                'state':   partner.state_id.name   if partner.state_id   else '',
                'country': partner.country_id.name if partner.country_id else '',
            },
            'start_date':    self.start_date.strftime('%d/%m/%Y'),
            'end_date':      self.end_date.strftime('%d/%m/%Y'),
            'opening_balance': round(opening_balance, 2),
            'lines':           lines,
            'net_balance':     round(running, 2),
            'docs':            self,
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def customer_statements_pdf_report(self):
        self.ensure_one()
        self._check_dates()
        return self.env.ref(
            'tk_statements.customer_report_template_action'
        ).report_action(self, data={'wizard_id': self.id})

    def customer_statements_excel_report(self):
        self.ensure_one()
        self._check_dates()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/customer_statement/excel?wizard_id={self.id}',
            'target': 'new',
        }
