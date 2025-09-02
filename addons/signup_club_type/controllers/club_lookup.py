# -- coding: utf-8 --
from odoo import http
from odoo.http import request

class ClubLookup(http.Controller):

    @http.route('/clubs/by_program', type='json', auth='public', csrf=False, website=True)
    def clubs_by_program(self, club_type=None, **kw):
        if not club_type:
            return []
        # Filter your contacts in res.partner
        domain = [
            ('club_type', '=', club_type),
            ('active', '=', True),
            # optionally narrow to organizations:
            # ('company_type', '=', 'company'),
        ]
        partners = request.env['res.partner'].sudo().search_read(domain, ['id', 'name'], order='name')
        # Ensure simple shape: [{"id": 123, "name": "Rotary Club ..."}, ...]
        return partners