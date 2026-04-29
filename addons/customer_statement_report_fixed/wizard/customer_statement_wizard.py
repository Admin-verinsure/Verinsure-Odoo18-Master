from odoo import models, fields
from datetime import date
import io, base64, xlsxwriter

class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'

    partner_id = fields.Many2one('res.partner', required=True)
    date_from = fields.Date(default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(default=fields.Date.today)
    report_type = fields.Selection([('pdf','PDF'),('xlsx','Excel')], default='pdf')

    file_data = fields.Binary()
    file_name = fields.Char()

    def _get_statement_data(self):
        moves = self.env['account.move'].search([
            ('partner_id','=',self.partner_id.id),
            ('state','=','posted'),
            ('move_type','in',['out_invoice','out_refund'])
        ])

        opening = sum(moves.filtered(lambda m: m.invoice_date and m.invoice_date < self.date_from).mapped('amount_total_signed'))
        period = moves.filtered(lambda m: m.invoice_date and self.date_from <= m.invoice_date <= self.date_to).sorted(key=lambda m:(m.invoice_date,m.id))

        balance = opening
        lines=[]
        for m in period:
            debit = m.amount_total if m.move_type=='out_invoice' else 0
            credit = m.amount_total if m.move_type=='out_refund' else 0
            balance += m.amount_total_signed
            lines.append({
                'date': m.invoice_date,
                'name': m.name,
                'type': 'Invoice' if m.move_type=='out_invoice' else 'Credit Note',
                'debit': debit,
                'credit': credit,
                'balance': balance,
            })

        return {
            'partner': self.partner_id.name,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'opening_balance': opening,
            'lines': lines,
            'closing_balance': balance,
        }

    def action_print_pdf(self):
        return self.env.ref('customer_statement_report.action_customer_statement_pdf').report_action(self)

    def action_export_xlsx(self):
        data = self._get_statement_data()
        company = self.env.company

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output)
        sheet = wb.add_worksheet('Statement')

        sheet.write('A1', company.name)
        sheet.write('A2', company.street or '')
        sheet.write('A3', company.street2 or '')
        sheet.write('A4', ' '.join(filter(None,[company.city,company.zip])))
        sheet.write('A5', company.country_id.name if company.country_id else '')

        row=7
        headers=['Date','Document','Type','Debit','Credit','Balance']
        for col,h in enumerate(headers):
            sheet.write(row,col,h)
        row+=1

        for l in data['lines']:
            sheet.write(row,0,str(l['date'] or ''))
            sheet.write(row,1,l['name'])
            sheet.write(row,2,l['type'])
            sheet.write(row,3,l['debit'])
            sheet.write(row,4,l['credit'])
            sheet.write(row,5,l['balance'])
            row+=1

        wb.close()
        output.seek(0)

        self.file_data = base64.b64encode(output.read())
        self.file_name = 'Customer_Statement.xlsx'

        return {
            'type':'ir.actions.act_window',
            'res_model':'customer.statement.wizard',
            'view_mode':'form',
            'res_id':self.id,
            'target':'new'
        }

    def action_generate(self):
        return self.action_print_pdf() if self.report_type=='pdf' else self.action_export_xlsx()
