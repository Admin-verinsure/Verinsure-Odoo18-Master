# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class ClubLookup(http.Controller):

    @http.route('/clubs/by_program', type='json', auth='public', csrf=False, website=True)
    def clubs_by_program(self, club_type=None, **kw):
        """Return active clubs filtered by selected program type"""
        if not club_type:
            return []
        domain = [
            ('club_type', '=', club_type),
            ('active', '=', True),
        ]
        partners = request.env['res.partner'].sudo().search_read(domain, ['id', 'name'], order='name')
        return partners
