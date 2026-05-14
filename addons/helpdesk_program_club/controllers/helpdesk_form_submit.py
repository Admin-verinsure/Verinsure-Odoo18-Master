# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from odoo.addons.odoo_website_helpdesk.controllers.main import WebsiteHelpdesk

_logger = logging.getLogger(__name__)


class WebsiteHelpdeskClub(WebsiteHelpdesk):
    """
    Extends the website helpdesk form submission controller so that
    `helpdesk_club_id` (a Many2one to res.partner) is included in the
    ticket vals when the public form is submitted.

    Odoo's base website-helpdesk controller only passes a hard-coded set
    of fields into ticket.create().  Any extra field not in that list is
    silently dropped — which is why Club Name never appears in the backend
    even though the JS sends the value correctly.

    We override `_get_ticket_form_values` (the method that builds the vals
    dict) to inject the club id, casting the raw string the HTML form sends
    into an int so the Many2one ORM field accepts it.
    """

    def _prepare_ticket_values(self, kwargs):
        """
        Called by the submit route. Extend the base vals dict with
        helpdesk_club_id if the form posted one.
        """
        vals = super()._prepare_ticket_values(kwargs) if hasattr(super(), '_prepare_ticket_values') else {}
        raw_club = kwargs.get('helpdesk_club_id')
        if raw_club:
            try:
                vals['helpdesk_club_id'] = int(raw_club)
            except (ValueError, TypeError):
                _logger.warning(
                    "helpdesk_form_submit: invalid helpdesk_club_id value %r — skipped", raw_club
                )
        return vals

    @http.route(
        '/helpdesk/submit',
        type='http',
        auth='public',
        methods=['POST'],
        website=True,
        csrf=True,
    )
    def submit_ticket(self, **kwargs):
        """
        Intercept the form POST so we can inject helpdesk_club_id into the
        kwargs before handing off to the parent controller.  The parent will
        call ticket.create() with whatever is in kwargs, and our model-level
        create() override (already present in models/helpdesk_ticket.py) will
        cast the string to int.
        """
        raw_club = kwargs.get('helpdesk_club_id')
        if raw_club:
            try:
                kwargs['helpdesk_club_id'] = int(raw_club)
            except (ValueError, TypeError):
                kwargs.pop('helpdesk_club_id', None)
                _logger.warning(
                    "submit_ticket: invalid helpdesk_club_id %r — removed from kwargs", raw_club
                )
        return super().submit_ticket(**kwargs)
