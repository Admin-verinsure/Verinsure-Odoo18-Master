from odoo import models, fields
from datetime import date

class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'

    partner_id = fields.Many2one('res.partner', required=True)
    date_from = fields.Date(default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(default=fields.Date.today)
    report_type = fields.Selection([('pdf','PDF'),('xlsx','Excel')], default='pdf')

    def action_generate(self):
        if self.report_type == 'pdf':
            return self.env.ref('customer_statement_report.action_customer_statement_pdf').report_action(self)
        return self._generate_xlsx()

    def _get_statement_data(self):
        domain = [
            ('partner_id','=',self.partner_id.id),
            ('state','=','posted'),
            ('move_type','in',['out_invoice','out_refund'])
        ]

        opening_moves = self.env['account.move'].search(domain+[('invoice_date','<',self.date_from)])
        opening_balance = sum(opening_moves.mapped('amount_residual_signed'))

        moves = self.env['account.move'].search(domain+[
            ('invoice_date','>=',self.date_from),
            ('invoice_date','<=',self.date_to)
        ], order='invoice_date,id')

        balance = opening_balance
        lines = [{
            'date':'',
            'name':'Opening Balance',
            'type':'',
            'debit':0,
            'credit':0,
            'balance':balance
        }]

        for move in moves:
            amount = move.amount_residual_signed
            debit = amount if amount>0 else 0
            credit = abs(amount) if amount<0 else 0
            balance += amount

            lines.append({
                'date':move.invoice_date,
                'name':move.name,
                'type':'Invoice' if move.move_type=='out_invoice' else 'Credit Note',
                'debit':debit,
                'credit':credit,
                'balance':balance
            })

        return {'lines':lines,'closing_balance':balance,'partner':self.partner_id}

    def _generate_xlsx(self):
        import io, base64, xlsxwriter
        from io import BytesIO

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        sheet = workbook.add_worksheet('Statement')

        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})

        data = self._get_statement_data()
        company = self.env.company

        row = 0

        if company.logo:
            image = BytesIO(base64.b64decode(company.logo))
            sheet.insert_image('A1', 'logo.png', {'image_data': image, 'x_scale':0.5,'y_scale':0.5})
            row = 6

        sheet.write(row,0,company.name,bold); row+=1
        sheet.write(row,0,company.street or ''); row+=1
        sheet.write(row,0,(company.city or '')+' '+(company.zip or '')); row+=2

        headers=['Date','Document','Type','Debit','Credit','Balance']
        for col,h in enumerate(headers):
            sheet.write(row,col,h,bold)
        row+=1

        for line in data['lines']:
            sheet.write(row,0,str(line['date']))
            sheet.write(row,1,line['name'])
            sheet.write(row,2,line['type'])
            sheet.write_number(row,3,line['debit'],money)
            sheet.write_number(row,4,line['credit'],money)
            sheet.write_number(row,5,line['balance'],money)
            row+=1

        workbook.close()
        output.seek(0)

        return {
            'type':'ir.actions.act_url',
            'url':"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"+base64.b64encode(output.read()).decode(),
            'target':'self'
        }
