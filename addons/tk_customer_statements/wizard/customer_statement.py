# -*- coding: utf-8 -*-
from io import BytesIO
import base64
from datetime import date
import xlwt
from odoo import fields, models
from odoo.exceptions import UserError


class CustomerStatementWizard(models.TransientModel):
    """
    A wizard for generating customer statement reports, including details such as invoices,
    payments, and balances for a specified date range.
    """
    _name = 'customer.statement.wizard'
    _description = "Customer Statement Report"
    _rec_name = 'start_date'

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        domain=[('invoice_ids', '!=', False)]
    )

    def customer_statements_pdf_report(self):
        """
        Generates a PDF report for the customer statement based on the selected date range.
        Raises an error if the start date is later than the end date.
        """
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError("Start date cannot be after the end date.")
        data = {
            'form_data': self.read()[0]
        }
        return self.env.ref('tk_customer_statements.customer_report_template_action').report_action(self, data=data)

    def customer_statements_excel_report(self):
        """
        Generates an Excel report for the customer statement, including invoice details,
        payments, and balances for a specified date range.
        """
        workbook = xlwt.Workbook(encoding="UTF-8")
        sheet1 = workbook.add_sheet('Stock-Report-Card', cell_overwrite_ok=True)
        main_head = xlwt.easyxf(
            'align: horiz center, vert center;'
            'pattern: pattern solid, fore_colour gray25;'
        )
        normal_heading = xlwt.easyxf(
            'font: bold on;'
            'align: horiz center,vert center;'
            'pattern: pattern solid, fore_colour gray25;'
        )
        normal_partner_data = xlwt.easyxf(
            'align: horiz center, vert center;'
        )
        normal_data = xlwt.easyxf(
            'align: horiz right, vert center;'
        )
        total_format = xlwt.easyxf(
            'align: horiz right, vert center;'
            'font: bold on;'
        )
        mege_cell_format = xlwt.easyxf(
            'font: height 170;'
            'align: horiz left, vert top, wrap on;'
            'borders: left thin, right thin, bottom thin, top thin;'
        )
        date_currency_format = xlwt.easyxf(
            'align: horiz left, vert center;'
            'borders: left thin, right thin, bottom thin, top thin;'
        )
        amount_format = xlwt.easyxf(
            'font: bold on;'
            'align: horiz right,vert center;'
            'pattern: pattern solid, fore_colour gray25;'
        )
        font = xlwt.Font()
        font.bold = True
        font.height = 310
        main_head.font = font

        date_head = xlwt.XFStyle()
        date_head.num_format_str = 'dd-mm-yyyy'
        alignment = xlwt.Alignment()
        alignment.horz = xlwt.Alignment.HORZ_LEFT
        alignment.vert = xlwt.Alignment.VERT_CENTER
        date_head.alignment = alignment
        borders = xlwt.Borders()
        borders.left = xlwt.Borders.THIN
        borders.right = xlwt.Borders.THIN
        borders.bottom = xlwt.Borders.THIN
        borders.top = xlwt.Borders.THIN
        date_head.borders = borders

        date_format = xlwt.XFStyle()
        date_format.num_format_str = 'dd-mm-yyyy'
        alignment = xlwt.Alignment()
        alignment.horz = xlwt.Alignment.HORZ_CENTER
        date_format.alignment = alignment

        sheet1.col(0).width = 5000
        sheet1.col(1).width = 5000
        sheet1.col(2).width = 5000
        sheet1.col(3).width = 5000
        sheet1.col(4).width = 5000
        sheet1.col(5).width = 5000
        sheet1.row(3).height = 400
        sheet1.row(4).height = 400
        sheet1.row(5).height = 400
        sheet1.row(7).height = 350

        company = self.env.company
        currency = company.currency_id.symbol

        invoices = self.env['account.move'].search([
            ('invoice_date', '>=', self.start_date),
            ('invoice_date', '<=', self.end_date),
            ('partner_id', '=', self.partner_id.id),
            ('move_type', '=', 'out_invoice')
        ])

        sheet1.write_merge(0, 1, 0, 5, 'Statement Of Account', main_head)
        sheet1.write(7, 0, "Invoice Date", normal_heading)
        sheet1.write(7, 1, "Due Date", normal_heading)
        sheet1.write(7, 2, "Invoice", normal_heading)
        sheet1.write(7, 3, "Invoice Amount", amount_format)
        sheet1.write(7, 4, "Payment Amount", amount_format)
        sheet1.write(7, 5, "Balance Due", amount_format)

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

        partner_data = ""
        if self.partner_id.name:
            partner_data += f"{self.partner_id.name}\n"
        if self.partner_id.street:
            partner_data += f"{self.partner_id.street}\n"
        if self.partner_id.street2:
            partner_data += f"{self.partner_id.street2}\n"
        if self.partner_id.city and self.partner_id.zip:
            partner_data += f"{self.partner_id.city}, {self.partner_id.zip}\n"
        elif self.partner_id.city:
            partner_data += f"{self.partner_id.city}\n"
        elif self.partner_id.zip:
            partner_data += f"{self.partner_id.zip}\n"
        if self.partner_id.state_id:
            partner_data += f"{self.partner_id.state_id.name}\n"
        if self.partner_id.country_id:
            partner_data += f"{self.partner_id.country_id.name}\n"

        sheet1.write_merge(3, 5, 0, 1, partner_data, mege_cell_format)
        sheet1.write(3, 4, "AS ON", date_currency_format)
        sheet1.write(3, 5, date.today(), date_head)
        sheet1.write(4, 4, "Currency", date_currency_format)
        sheet1.write(4, 5, currency, date_currency_format)

        row_start = 8
        for invoice in invoice_data:
            sheet1.write(row_start, 0, invoice['invoice_date'], date_format)
            sheet1.write(row_start, 1, invoice['due_date'], date_format)
            sheet1.write(row_start, 2, invoice['invoice_id'], normal_partner_data)
            sheet1.write(row_start, 3, invoice['amount'], normal_data)
            sheet1.write(row_start, 4, invoice['payment_amount'], normal_data)
            sheet1.write(row_start, 5, invoice['balance_due'], normal_data)
            sheet1.row(row_start).height = 300
            row_start += 1
        sheet1.row(row_start).height = 300
        sheet1.write_merge(row_start, row_start, 0, 2, 'Total', amount_format)
        sheet1.write(row_start, 3, round(total_amount, 2), total_format)
        sheet1.write(row_start, 4, round(total_payment, 2), total_format)
        sheet1.write(row_start, 5, round(total_balance, 2), total_format)

        stream = BytesIO()
        workbook.save(stream)
        filename = "Customer Statement Report" + ".xls"
        output = base64.encodebytes(stream.getvalue())
        attachment = self.env['ir.attachment'].sudo()
        attachment_id = attachment.create({
            'name': filename,
            'type': "binary",
            'public': False,
            'datas': output
        })
        if attachment_id:
            report = {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%s?download=true' % (attachment_id.id),
                'target': 'self'
            }
            return report
