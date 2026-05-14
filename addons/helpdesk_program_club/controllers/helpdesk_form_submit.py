# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Try to import the base controller — the path varies by community module version
_BaseController = None
_base_method_name = None

try:
    from odoo.addons.odoo_website_helpdesk.controllers.main import WebsiteHelpdesk as _BaseController
    _base_method_name = 'submit_ticket'
    _logger.info("helpdesk_program_club: using odoo_website_helpdesk.controllers.main.WebsiteHelpdesk")
except ImportError:
    pass

if _BaseController is None:
    try:
        from odoo.addons.odoo_website_helpdesk.controllers.helpdesk import WebsiteHelpdesk as _BaseController
        _base_method_name = 'submit_ticket'
        _logger.info("helpdesk_program_club: using odoo_website_helpdesk.controllers.helpdesk.WebsiteHelpdesk")
    except ImportError:
        pass

if _BaseController is None:
    _logger.warning(
        "helpdesk_program_club: Could not import base WebsiteHelpdesk controller. "
        "Club field will be saved via model-layer override only."
    )


if _BaseController is not None:
    class WebsiteHelpdeskClub(_BaseController):

        @http.route()
        def submit_ticket(self, **kw):
            # Cast helpdesk_club_id string → int before super() drops it
            raw_club = kw.get('helpdesk_club_id', '')
            if isinstance(raw_club, str):
                raw_club = raw_club.strip()
            if raw_club and str(raw_club) not in ('0', 'False', 'false', ''):
                try:
                    kw['helpdesk_club_id'] = int(raw_club)
                except (ValueError, TypeError):
                    _logger.warning("Cannot cast helpdesk_club_id=%r", raw_club)
                    kw.pop('helpdesk_club_id', None)
            else:
                kw.pop('helpdesk_club_id', None)

            if 'helpdesk_program_type' in kw and not kw['helpdesk_program_type']:
                kw.pop('helpdesk_program_type', None)

            return super().submit_ticket(**kw)
