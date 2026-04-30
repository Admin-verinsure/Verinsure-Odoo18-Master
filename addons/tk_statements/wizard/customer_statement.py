# -*- coding: utf-8 -*-
from datetime import date
from odoo import fields, models, api
from odoo.exceptions import UserError


class CustomerStatementWizard(models.TransientModel):
    """
    Wizard for generating Customer Statement Reports.

    Supports:
    - Date range filtering (start_date / end_date)
    - Posted invoices (out_invoice) and credit notes (out_refund)
    - Running balance ledger
    - Opening balance (outstanding before start_date)
    - Partial payment handling via amount_residual_signed
    - PDF output (QWeb / external_layout)
    - Excel output (via controller route, no base64 URL payload)
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
        """
        Returns a dict with all data needed to render PDF or Excel:

        {
            'company': {'name': ..., 'address': ...},
            'partner': {'name': ..., 'street': ..., ...},
            'start_date': str,
            'end_date': str,
            'opening_balance': float,
            'lines': [
                {
                    'date': date,
                    'name': str,          # document number
                    'move_type': str,     # out_invoice / out_refund
                    'type_label': str,    # "Invoice" / "Credit Note"
                    'debit': float|None,
                    'credit': float|None,
                    'running_balance': float,
                }
            ],
            'net_balance': float,
        }
        """
        self.ensure_one()
        self._check_dates()

        domain_base = [
            ('partner_id', 'child_of', self.partner_id.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
        ]

        # ---- Opening balance: all posted moves BEFORE start_date ----
        opening_moves = self.env['account.move'].search(
            domain_base + [('invoice_date', '<', self.start_date)],
            order='invoice_date asc, name asc',
        )
        opening_balance = 0.0
        for move in opening_moves:
            if move.move_type == 'out_invoice':
                opening_balance += move.amount_residual
            else:  # out_refund
                opening_balance -= move.amount_residual

        # ---- Period moves ----
        period_domain = domain_base + [
            ('invoice_date', '>=', self.start_date),
            ('invoice_date', '<=', self.end_date),
        ]
        if not self.include_zero_balance:
            # Still show all moves in the period regardless of residual,
            # but allow the user to hide fully-settled ones if desired.
            pass  # default: include all

        period_moves = self.env['account.move'].search(
            period_domain,
            order='invoice_date asc, name asc',
        )

        lines = []
        running = opening_balance
        for move in period_moves:
            residual = move.amount_residual  # always positive in Odoo
            paid = move.amount_total - residual

            if move.move_type == 'out_invoice':
                debit = move.amount_total
                credit = paid if paid > 0 else None
                running += residual          # add the outstanding portion
                type_label = "Invoice"
            else:  # out_refund
                debit = None
                credit = move.amount_total
                running -= residual          # reduce the outstanding balance
                type_label = "Credit Note"

            # Skip fully paid if user opted out
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

        # ---- Company ----
        company = self.env.company
        addr_parts = filter(None, [
            company.street, company.street2,
            company.city, company.zip,
            company.state_id.name if company.state_id else None,
            company.country_id.name if company.country_id else None,
        ])
        company_address = ', '.join(addr_parts)

        # ---- Partner ----
        partner = self.partner_id
        net_balance = round(running, 2)

        return {
            'company': {
                'name': company.name,
                'address': company_address,
                'currency_symbol': company.currency_id.symbol,
            },
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
            'net_balance': net_balance,
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def customer_statements_pdf_report(self):
        """Trigger QWeb PDF report."""
        self.ensure_one()
        self._check_dates()
        data = {'wizard_id': self.id}
        return self.env.ref(
            'tk_statements.customer_report_template_action'
        ).report_action(self, data=data)

    def customer_statements_excel_report(self):
        """
        Open the Excel download URL (controller route).
        The controller reads the wizard by ID — no large payload in the URL.
        """
        self.ensure_one()
        self._check_dates()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/customer_statement/excel?wizard_id={self.id}',
            'target': 'self',
        }
