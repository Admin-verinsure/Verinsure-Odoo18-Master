from odoo import http
from odoo.http import request

class ZentechDynamicSources(http.Controller):

    @http.route(
        "/zentech/options/volunteer",
        type="json",
        auth="public",
        csrf=False,
    )
    def volunteer_options(self):
        employees = request.env["hr.employee"].sudo().search([
            ("active", "=", True),
        ], order="name asc")

        return [
            {
                "value": emp.id,
                "label": emp.name,
            }
            for emp in employees
        ]
