# -*- coding: utf-8 -*-
from datetime import date
from odoo import models, api


class InvoiceAbstractReport(models.AbstractModel):
    """
    Abstract model for generating customer invoice reports,
    including invoice details, payments, and balances.
    """
    _name = 'report.tk_customer_statements.customer_report_template'
    _description = 'Invoice Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        """
        Retrieves customer invoice data for a specific partner within a given date range,
        calculates total amounts, payments, and balances, and provides relevant customer details.
        """
        company = self.env.company
        currency = company.currency_id.symbol
        start_date = data.get('form_data').get('start_date')
        end_date = data.get('form_data').get('end_date')
        partner_id = data.get('form_data').get('partner_id')
        invoices = self.env['account.move'].search([
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('partner_id', '=', partner_id[0]),
            ('move_type', '=', 'out_invoice')
        ])

        invoice_data = []
        total_amount = 0
        total_payment = 0
        total_balance = 0

        for invoice in invoices:
            paid_amount = invoice.amount_total - invoice.amount_residual

            invoice_info = {
                'invoice_date': invoice.invoice_date,
                'due_date': invoice.invoice_date_due,
                'invoice_id': invoice.name,
                'partner': invoice.partner_id.name,
                'amount': round(invoice.amount_total, 2),
                'payment_amount': round(paid_amount, 2),
                'balance_due': round(invoice.amount_residual, 2),
            }

            invoice_data.append(invoice_info)
            total_amount += invoice.amount_total
            total_payment += paid_amount
            total_balance += invoice.amount_residual

        return {
            'docs': invoice_data,
            'total_amount': round(total_amount, 2),
            'total_payment': round(total_payment, 2),
            'total_balance': round(total_balance, 2),
            'partner_name': partner_id[1],
            'partner_street': invoices.partner_id[0].street,
            'partner_street2': invoices.partner_id[0].street2,
            'partner_zip': invoices.partner_id[0].zip,
            'partner_city': invoices.partner_id[0].city,
            'partner_state_id': invoices.partner_id[0].state_id.name,
            'partner_country_id': invoices.partner_id[0].country_id.name,
            'today_date': date.today(),
            'currency': currency,
        }
