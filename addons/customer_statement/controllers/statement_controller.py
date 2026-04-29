from odoo import http
from odoo.http import request, content_disposition

class StatementController(http.Controller):

    @http.route('/customer_statement/excel/<int:wizard_id>', type='http', auth='user')
    def download_excel(self, wizard_id, **kwargs):
        wizard = request.env['customer.statement.wizard'].browse(wizard_id)
        content = wizard.generate_excel_file()

        return request.make_response(
            content,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition('Customer_Statement.xlsx'))
            ]
        )
