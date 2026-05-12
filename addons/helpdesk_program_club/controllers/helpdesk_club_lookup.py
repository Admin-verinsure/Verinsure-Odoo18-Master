# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HelpdeskClubLookup(http.Controller):
    """
    Public JSON endpoint that returns the list of active clubs
    filtered by a given club_type (Program Type) value.

    Called by helpdesk_club_fill.js whenever the user changes
    the Program Type <select> on the helpdesk webform.

    Route: POST /helpdesk/clubs_by_type
    Payload (JSON-RPC 2.0):
        { "params": { "club_type": "<selection_key>" } }
    Response:
        [ { "id": 123, "name": "Club Name" }, … ]
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
            _logger.warning("helpdesk clubs_by_type: no club_type received")
            return []

        domain = [
            ('club_type', '=', club_type),
            ('active', '=', True),
        ]

        try:
            partners = request.env['res.partner'].sudo().search_read(
                domain,
                ['id', 'name'],
                order='name',
            )
            _logger.info(
                "helpdesk clubs_by_type: %s clubs for club_type=%s",
                len(partners), club_type,
            )
            return partners   # already [{"id": N, "name": "…"}, …]
        except Exception as exc:
            request.env.cr.rollback()
            _logger.exception("helpdesk clubs_by_type failed: %s", exc)
            return []
