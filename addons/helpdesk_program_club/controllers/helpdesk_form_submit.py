# -*- coding: utf-8 -*-
# controllers/helpdesk_form_submit.py
#
# Inherits the website helpdesk submit controller so that our custom field
# `helpdesk_club_id` is explicitly injected into the ticket vals before
# create() is called.
#
# WHY THIS IS NEEDED:
#   Odoo's base WebsiteHelpdesk.submit_ticket() builds the ticket dict from
#   a fixed set of known kwargs — it does NOT blindly forward every POST param.
#   Custom fields are silently ignored unless you override the method and
#   add them yourself.

import logging
from odoo import http
from odoo.http import request
from odoo.addons.odoo_website_helpdesk.controllers.main import WebsiteHelpdesk

_logger = logging.getLogger(__name__)


class WebsiteHelpdeskClub(WebsiteHelpdesk):

    @http.route()   # keeps the same route(s) from parent — no redeclaration needed
    def submit_ticket(self, **kw):
        """
        Inject helpdesk_club_id into POST values before the parent controller
        creates the ticket. The HTML <select> sends it as a plain string ID.
        """
        # helpdesk_club_id arrives as a string like "42" from the HTML select
        raw_club = kw.get('helpdesk_club_id', '')
        if isinstance(raw_club, str):
            raw_club = raw_club.strip()

        if raw_club and str(raw_club) not in ('0', 'False', 'false', ''):
            try:
                kw['helpdesk_club_id'] = int(raw_club)
            except (ValueError, TypeError):
                _logger.warning(
                    "submit_ticket: cannot cast helpdesk_club_id=%r to int", raw_club
                )
                kw.pop('helpdesk_club_id', None)
        else:
            kw.pop('helpdesk_club_id', None)   # don't send junk to create()

        # helpdesk_program_type is a Char/Selection — pass as-is, but drop if empty
        if 'helpdesk_program_type' in kw and not kw['helpdesk_program_type']:
            kw.pop('helpdesk_program_type', None)

        return super().submit_ticket(**kw)
