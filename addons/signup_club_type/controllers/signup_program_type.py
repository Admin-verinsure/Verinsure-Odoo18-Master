from odoo import http
from odoo.http import request

class SignupProgramType(http.Controller):

    @http.route('/signup/club_type_selection', type='json', auth='public', csrf=False, website=True)
    def club_type_selection(self):
        """Return the res.partner.club_type selection as [{'value':..,'label':..}]"""
        field_info = request.env['res.partner'].sudo().fields_get(['club_type'])
        selection = field_info['club_type']['selection'] if field_info and 'club_type' in field_info else []
        return [{'value': v, 'label': l} for (v, l) in selection]
