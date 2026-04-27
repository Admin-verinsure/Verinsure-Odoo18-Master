# -*- coding: utf-8 -*-
from datetime import date
from odoo import models, api


class InvoiceAbstractReport(models.AbstractModel):
    """
    Abstract model for generating customer invoice reports,
    including invoice details, credit notes, payments, and balances.
    """
    _name = 'report.tk_customer_statements.customer_report_template'
    _description = 'Invoice Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        """
        Retrieves customer invoice and credit note data for a specific partner within a given
        date range, calculates total amounts, payments, and balances, and provides relevant
        customer details.
        """
        company = self.env.company
        currency = company.currency_id.symbol
        start_date = data.get('form_data').get('start_date')
        end_date = data.get('form_data').get('end_date')
        partner_id = data.get('form_data').get('partner_id')
        include_credit_notes = data.get('form_data', {}).get('include_credit_notes', False)

        move_types = ['out_invoice']
        if include_credit_notes:
            move_types.append('out_refund')

        moves = self.env['account.move'].search([
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('partner_id', '=', partner_id[0]),
            ('move_type', 'in', move_types),
            ('state', '=', 'posted'),
        ], order='invoice_date asc, name asc')

        invoice_data = []
        total_amount = 0
        total_payment = 0
        total_balance = 0

        for move in moves:
            is_credit_note = move.move_type == 'out_refund'
            paid_amount = move.amount_total - move.amount_residual
            # Credit notes carry a negative sign to correctly reduce totals
            sign = -1 if is_credit_note else 1

            move_info = {
                'invoice_date': move.invoice_date,
                'due_date': move.invoice_date_due,
                'invoice_id': move.name,
                'move_type_label': 'Credit Note' if is_credit_note else 'Invoice',
                'is_credit_note': is_credit_note,
                'amount': round(move.amount_total * sign, 2),
                'payment_amount': round(paid_amount * sign, 2),
                'balance_due': round(move.amount_residual * sign, 2),
            }

            invoice_data.append(move_info)
            total_amount += move.amount_total * sign
            total_payment += paid_amount * sign
            total_balance += move.amount_residual * sign

        # Safely resolve partner details — fallback to empty strings if no moves found
        partner = self.env['res.partner'].browse(partner_id[0])

        return {
            'docs': invoice_data,
            'include_credit_notes': include_credit_notes,
            'total_amount': round(total_amount, 2),
            'total_payment': round(total_payment, 2),
            'total_balance': round(total_balance, 2),
            'partner_name': partner_id[1],
            'partner_street': partner.street or '',
            'partner_street2': partner.street2 or '',
            'partner_zip': partner.zip or '',
            'partner_city': partner.city or '',
            'partner_state_id': partner.state_id.name if partner.state_id else '',
            'partner_country_id': partner.country_id.name if partner.country_id else '',
            'today_date': date.today(),
            'currency': currency,
        }
