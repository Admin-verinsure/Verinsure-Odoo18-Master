# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class ClubLookup(http.Controller):

    @http.route('/clubs/by_program', type='json', auth='public', csrf=False, website=True)
    def clubs_by_program(self, club_type=None, program_type=None, **kw):
        """
        Return active clubs filtered by selected program type or club type.
        Works with both old (club_type) and new (program_type) parameter names.
        """
        # Accept either parameter for backward compatibility
        club_type = club_type or program_type
        if not club_type:
            return []

        domain = [
            ('club_type', '=', club_type),
            ('active', '=', True),
        ]

        try:
            # Fetch clubs; include club_name if available
            partners = request.env['res.partner'].sudo().search_read(domain, ['id', 'club_name', 'name'], order='club_name')
            # Fallback to 'name' if 'club_name' missing
            return [{'id': p['id'], 'name': p.get('club_name') or p['name']} for p in partners]
        except Exception as e:
            request.env.cr.rollback()
            return []
