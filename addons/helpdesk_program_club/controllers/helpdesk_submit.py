# -*- coding: utf-8 -*-
"""
Extends the Helpdesk website form controller so that when a ticket is
submitted via the public website form, the two extra POST fields
  - program_type      (selection key, e.g. "rotary")
  - ticket_club_id    (res.partner id as string, e.g. "42")
are written onto the new helpdesk.ticket record.
"""
from odoo import http
from odoo.http import request
from odoo.addons.website_helpdesk.controllers.main import WebsiteHelpdesk


class WebsiteHelpdeskExtended(WebsiteHelpdesk):

    # ------------------------------------------------------------------
    # Override the ticket-creation endpoint
    # Odoo 18 website_helpdesk uses /helpdesk/submit (type='http')
    # ------------------------------------------------------------------
    @http.route(
        "/helpdesk/submit",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def website_helpdesk_submit(self, **post):
        # Extract our custom fields BEFORE calling super so they don't
        # confuse the parent's field-mapping logic (unknown fields raise).
        program_type  = post.pop("program_type", None) or False
        club_id_raw   = post.pop("ticket_club_id", None)

        try:
            club_id = int(club_id_raw) if club_id_raw else False
        except (ValueError, TypeError):
            club_id = False

        # Let the standard controller create the ticket
        response = super().website_helpdesk_submit(**post)

        # Write our extra fields onto the most recently created ticket
        # for this session (same approach Odoo uses internally).
        if program_type or club_id:
            ticket = self._get_last_created_ticket()
            if ticket:
                vals = {}
                if program_type:
                    vals["program_type"] = program_type
                if club_id:
                    # Verify the partner still exists and club_type matches
                    partner = (
                        request.env["res.partner"]
                        .sudo()
                        .browse(club_id)
                        .exists()
                    )
                    if partner:
                        vals["ticket_club_id"] = partner.id
                if vals:
                    ticket.sudo().write(vals)

        return response

    # ------------------------------------------------------------------
    # Helper – retrieve the ticket we just created
    # ------------------------------------------------------------------
    def _get_last_created_ticket(self):
        """
        The parent controller stores the new ticket id in the session
        under 'last_helpdesk_ticket_id' (Odoo 18 convention).
        Fall back to searching by create_uid / create_date if missing.
        """
        ticket_id = request.session.get("last_helpdesk_ticket_id")
        if ticket_id:
            ticket = (
                request.env["helpdesk.ticket"]
                .sudo()
                .browse(ticket_id)
                .exists()
            )
            if ticket:
                return ticket

        # Fallback: newest ticket created in the last 30 s by this user
        ticket = (
            request.env["helpdesk.ticket"]
            .sudo()
            .search(
                [("create_uid", "=", request.env.uid)],
                order="create_date desc",
                limit=1,
            )
        )
        return ticket or None
