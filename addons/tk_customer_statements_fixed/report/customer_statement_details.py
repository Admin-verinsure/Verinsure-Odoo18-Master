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
        moves = self.env['account.move'].search([
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('partner_id', '=', partner_id[0]),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
        ], order='invoice_date asc')

        invoice_data = []
        total_amount = 0
        total_payment = 0
        total_balance = 0

        for move in moves:
            is_credit_note = move.move_type == 'out_refund'
            # Credit notes reduce amounts (negative sign)
            sign = -1 if is_credit_note else 1
            paid_amount = move.amount_total - move.amount_residual

            invoice_info = {
                'invoice_date': move.invoice_date,
                'due_date': move.invoice_date_due,
                'invoice_id': move.name,
                'partner': move.partner_id.name,
                'amount': round(sign * move.amount_total, 2),
                'payment_amount': round(sign * paid_amount, 2),
                'balance_due': round(sign * move.amount_residual, 2),
                'is_credit_note': is_credit_note,
            }

            invoice_data.append(invoice_info)
            total_amount += sign * move.amount_total
            total_payment += sign * paid_amount
            total_balance += sign * move.amount_residual

        partner = self.env['res.partner'].browse(partner_id[0])
        return {
            'docs': invoice_data,
            'total_amount': round(total_amount, 2),
            'total_payment': round(total_payment, 2),
            'total_balance': round(total_balance, 2),
            'partner_name': partner_id[1],
            'partner_street': partner.street or '',
            'partner_street2': partner.street2 or '',
            'partner_zip': partner.zip or '',
            'partner_city': partner.city or '',
            'partner_state_id': partner.state_id.name or '',
            'partner_country_id': partner.country_id.name or '',
            'today_date': date.today(),
            'currency': currency,
        }
