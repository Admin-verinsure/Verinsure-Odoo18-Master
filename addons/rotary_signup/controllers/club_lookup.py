# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class ClubLookup(http.Controller):

    @http.route('/club_lookup', type='json', auth='public', csrf=False, website=True)
    def club_lookup(self, program_type_id=None, **kw):
        """
        Return active clubs filtered by selected program type.
        JS calls this with { program_type_id: int }.
        """
        if not program_type_id:
            _logger.warning("No program_type_id received in /club_lookup")
            return []

        domain = [
            ('program_type_id', '=', int(program_type_id)),
            ('active', '=', True),
        ]

        try:
            partners = request.env['res.partner'].sudo().search_read(domain, ['id', 'club_name', 'name'], order='club_name')
            clubs = [{'id': p['id'], 'name': p.get('club_name') or p['name']} for p in partners]
            _logger.info("club_lookup returned %s clubs for program_type_id=%s", len(clubs), program_type_id)
            return clubs
        except Exception as e:
            request.env.cr.rollback()
            _logger.exception("club_lookup failed: %s", e)
            return []
