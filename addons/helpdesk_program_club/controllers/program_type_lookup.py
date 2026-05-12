# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HelpdeskProgramTypeLookup(http.Controller):
    """
    Returns the list of program types from res.partner.club_type selection.
    Called by JS to populate the Program Type dropdown when the arch is
    a static DB blob (no QWeb t-foreach at render time).
    """

    @http.route(
        '/helpdesk/program_types',
        type='json',
        auth='public',
        csrf=False,
        website=True,
    )
    def program_types(self, **kw):
        field = request.env['res.partner']._fields.get('club_type')
        if not field:
            return []
        selection = field.selection
        if callable(selection):
            selection = selection(request.env['res.partner'])
        return [{'value': k, 'label': v} for k, v in (selection or [])]
