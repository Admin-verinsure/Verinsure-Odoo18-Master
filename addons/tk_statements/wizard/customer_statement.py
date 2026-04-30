# -*- coding: utf-8 -*-
from datetime import date
from odoo import fields, models, api
from odoo.exceptions import UserError


 
 
class CustomerStatementWizard(models.TransientModel):

    _name = 'customer.statement.wizard'

    _description = "Customer Statement Report"

    _rec_name = 'partner_id'
 
    # ---------------------------------------------------------

    # Fields

    # ---------------------------------------------------------
 
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
 
    # ---------------------------------------------------------

    # Validation

    # ---------------------------------------------------------
 
    def _check_dates(self):

        self.ensure_one()

        if self.start_date > self.end_date:

            raise UserError("Start Date cannot be later than End Date.")
 
    # ---------------------------------------------------------

    # Core Data Builder (Single Source of Truth)

    # ---------------------------------------------------------
 
    def _get_statement_data(self):

        self.ensure_one()

        self._check_dates()
 
        domain_base = [

            ('partner_id', 'child_of', self.partner_id.id),

            ('move_type', 'in', ['out_invoice', 'out_refund']),

            ('state', '=', 'posted'),

        ]
 
        # -----------------------------

        # Opening Balance

        # -----------------------------

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
 
        # -----------------------------

        # Period Moves

        # -----------------------------

        period_moves = self.env['account.move'].search(

            domain_base + [

                ('invoice_date', '>=', self.start_date),

                ('invoice_date', '<=', self.end_date),

            ],

            order='invoice_date asc, name asc',

        )
 
        lines = []

        running = opening_balance
 
        for move in period_moves:

            residual = move.amount_residual

            paid = move.amount_total - residual
 
            if move.move_type == 'out_invoice':

                debit = move.amount_total

                credit = paid if paid > 0 else None

                running += residual

                type_label = "Invoice"
 
            else:

                debit = None

                credit = move.amount_total

                running -= residual

                type_label = "Credit Note"
 
            if not self.include_zero_balance and residual == 0:

                continue
 
            lines.append({

                'date': move.invoice_date,

                'name': move.name,

                'move_type': move.move_type,

                'type_label': type_label,

                'debit': round(debit, 2) if debit else None,

                'credit': round(credit, 2) if credit else None,

                'running_balance': round(running, 2),

            })
 
        # -----------------------------

        # Company Info

        # -----------------------------

        company_rec = self.env.company
 
        addr_parts = filter(None, [

            company_rec.street,

            company_rec.street2,

            company_rec.city,

            company_rec.zip,

            company_rec.state_id.name if company_rec.state_id else None,

            company_rec.country_id.name if company_rec.country_id else None,

        ])
 
        company_info = {

            'name': company_rec.name,

            'address': ', '.join(addr_parts),

            'currency_symbol': company_rec.currency_id.symbol,

        }
 
        # -----------------------------

        # Partner Info

        # -----------------------------

        partner = self.partner_id
 
        return {

            'company': company_rec,

            'company_info': company_info,

            'partner': {

                'name': partner.name,

                'street': partner.street or '',

                'street2': partner.street2 or '',

                'city': partner.city or '',

                'zip': partner.zip or '',

                'state': partner.state_id.name if partner.state_id else '',

                'country': partner.country_id.name if partner.country_id else '',

            },

            'start_date': self.start_date.strftime('%d/%m/%Y'),

            'end_date': self.end_date.strftime('%d/%m/%Y'),

            'opening_balance': round(opening_balance, 2),

            'lines': lines,

            'net_balance': round(running, 2),

            'docs': self,

        }
 
    # ---------------------------------------------------------

    # Actions

    # ---------------------------------------------------------
 
    def customer_statements_pdf_report(self):

        """Original PDF (keep untouched)"""

        self.ensure_one()

        self._check_dates()

        return self.env.ref(

            'tk_statements.customer_report_template_action'

        ).report_action(self, data={'wizard_id': self.id})
 
    def customer_statements_excel_report(self):

        """Original Excel (keep untouched)"""

        self.ensure_one()

        self._check_dates()

        return {

            'type': 'ir.actions.act_url',

            'url': f'/customer_statement/excel?wizard_id={self.id}',

            'target': 'self',

        }
 
    # ---------------------------------------------------------

    # NEW LEDGER PDF

    # ---------------------------------------------------------
 
    def action_print_customer_ledger(self):

        """New Ledger-style PDF"""

        self.ensure_one()

        self._check_dates()
 
        return self.env.ref(

            'tk_customer_statements.action_custom_customer_ledger'

        ).report_action(self, data={'wizard_id': self.id})
 