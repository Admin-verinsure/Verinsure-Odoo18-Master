from odoo import http
from odoo.http import request

class DynamicFormController(http.Controller):

    @http.route("/dynamic_form/<int:form_id>", auth="public", website=True)
    def render_form(self, form_id):
        form = request.env["dynamic.form"].sudo().browse(form_id)
        return request.render(
            "dynamic_form_builder.public_form_template",
            {"form": form},
        )