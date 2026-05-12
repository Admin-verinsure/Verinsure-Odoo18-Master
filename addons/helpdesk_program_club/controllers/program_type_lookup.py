# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HelpdeskProgramTypeLookup(http.Controller):
    """
    Returns program type options from res.partner.club_type selection field.
    Called by JS on page load to populate the Program Type dropdown.
    Same source as signup_club_type module.
    """

    @http.route(
        '/helpdesk/program_types',
        type='json',
        auth='public',
        csrf=False,
        website=True,
    )
    def program_types(self, **kw):
        try:
            field = request.env['res.partner']._fields.get('club_type')
            if not field:
                _logger.warning("program_types: club_type not found on res.partner")
                return []
            selection = field.selection
            if callable(selection):
                selection = selection(request.env['res.partner'])
            result = [{'value': k, 'label': v} for k, v in (selection or [])]
            _logger.info("program_types: returning %s options", len(result))
            return result
        except Exception as e:
            _logger.exception("program_types error: %s", e)
            return []
