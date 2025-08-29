from odoo import http
from odoo.http import request

class SignupClubTypeController(http.Controller):

    @http.route('/signup/club_type_selection', type='json', auth='public', website=True, csrf=False)
    def club_type_selection(self):
        # Read selection from res.partner.club_type
        sel = request.env['res.partner']._fields['club_type'].selection
        # Return list of dicts for the JS to render
        return [{"value": value, "label": label} for value, label in sel]
