from odoo import models, fields
from datetime import date
import io
import base64
import xlsxwriter

class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'

    partner_id = fields.Many2one('res.partner', required=True)
    date_from = fields.Date(default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(default=fields.Date.today)
    report_type = fields.Selection([('pdf', 'PDF'), ('xlsx', 'Excel')], default='pdf')

    file_data = fields.Binary("File")
    file_name = fields.Char("Filename")

    def _get_statement_data(self):
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', ['out_invoice', 'out_refund'])
        ]
        moves = self.env['account.move'].search(domain)

        opening_moves = moves.filtered(lambda m: m.invoice_date and m.invoice_date < self.date_from)
        opening_balance = sum(opening_moves.mapped('amount_total_signed'))

        period_moves = moves.filtered(lambda m: m.invoice_date and self.date_from <= m.invoice_date <= self.date_to)
        moves_sorted = period_moves.sorted(key=lambda m: (m.invoice_date, m.id))

        balance = opening_balance
        lines = []

        for move in moves_sorted:
            debit = move.amount_total if move.move_type == 'out_invoice' else 0
            credit = move.amount_total if move.move_type == 'out_refund' else 0
            balance += move.amount_total_signed

            lines.append({
                'date': move.invoice_date,
                'name': move.name,
                'type': 'Invoice' if move.move_type == 'out_invoice' else 'Credit Note',
                'debit': debit,
                'credit': credit,
                'balance': balance,
            })

        return {
            'partner': self.partner_id.name,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'opening_balance': opening_balance,
            'lines': lines,
            'closing_balance': balance,
        }

    def action_print_pdf(self):
        return self.env.ref('customer_statement_report.action_customer_statement_pdf').report_action(self)

    def action_export_xlsx(self):
        data = self._get_statement_data()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        sheet = workbook.add_worksheet('Statement')

        bold = workbook.add_format({'bold': True})

        row = 0
        sheet.write(row, 0, 'Customer', bold)
        sheet.write(row, 1, data['partner'])

        row += 2
        headers = ['Date', 'Document', 'Type', 'Debit', 'Credit', 'Balance']
        for col, h in enumerate(headers):
            sheet.write(row, col, h, bold)

        row += 1
        for line in data['lines']:
            sheet.write(row, 0, str(line['date'] or ''))
            sheet.write(row, 1, line['name'])
            sheet.write(row, 2, line['type'])
            sheet.write(row, 3, line['debit'])
            sheet.write(row, 4, line['credit'])
            sheet.write(row, 5, line['balance'])
            row += 1

        row += 1
        sheet.write(row, 4, 'Closing Balance', bold)
        sheet.write(row, 5, data['closing_balance'])

        workbook.close()
        output.seek(0)

        self.file_data = base64.b64encode(output.read())
        self.file_name = 'Customer_Statement.xlsx'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'customer.statement.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def action_generate(self):
        if self.report_type == 'pdf':
            return self.action_print_pdf()
        return self.action_export_xlsx()
