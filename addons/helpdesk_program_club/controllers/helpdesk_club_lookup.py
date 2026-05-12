# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HelpdeskClubLookup(http.Controller):
    """
    Returns clubs filtered by club_type from res.partner.
    Called by JS on Program Type change.
    Mirrors /club_lookup from rotary_signup module.
    """

    @http.route(
        '/helpdesk/clubs_by_type',
        type='json',
        auth='public',
        csrf=False,
        website=True,
    )
    def clubs_by_type(self, club_type=None, **kw):
        if not club_type:
            return []
        try:
            partners = request.env['res.partner'].sudo().search_read(
                [('club_type', '=', club_type), ('active', '=', True)],
                ['id', 'name'],
                order='name',
            )
            _logger.info(
                "clubs_by_type: %s clubs for club_type=%s", len(partners), club_type
            )
            return partners
        except Exception as e:
            _logger.exception("clubs_by_type error: %s", e)
            return []
