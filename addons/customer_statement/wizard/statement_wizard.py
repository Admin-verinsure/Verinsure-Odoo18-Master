from odoo import models, fields
import io
import xlsxwriter

class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'

    partner_id = fields.Many2one('res.partner', required=True)
    date_from = fields.Date()
    date_to = fields.Date()

    def _get_moves(self):
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted')
        ]
        if self.date_from:
            domain.append(('invoice_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('invoice_date', '<=', self.date_to))
        return self.env['account.move'].search(domain, order='invoice_date')

    def action_generate_pdf(self):
        return self.env.ref('customer_statement.action_customer_statement_pdf').report_action(self)

    def action_generate_excel(self):
        return {
            'type': 'ir.actions.act_url',
            'url': f'/customer_statement/excel/{self.id}',
            'target': 'self',
        }

    def generate_excel_file(self):
        moves = self._get_moves()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Statement')

        bold = workbook.add_format({'bold': True})
        sheet.write(0, 0, 'Customer Statement', bold)
        sheet.write(1, 0, self.partner_id.name)

        row = 3
        sheet.write_row(row, 0, ['Date','Type','Number','Debit','Credit','Balance'], bold)

        balance = 0
        row += 1

        for m in moves:
            debit = m.amount_total if m.move_type == 'out_invoice' else 0
            credit = m.amount_total if m.move_type == 'out_refund' else 0
            balance += debit - credit

            sheet.write_row(row, 0, [
                str(m.invoice_date),
                m.move_type,
                m.name,
                debit,
                credit,
                balance
            ])
            row += 1

        workbook.close()
        output.seek(0)
        return output.read()
