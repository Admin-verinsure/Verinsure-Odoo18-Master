# -*- coding: utf-8 -*-
"""
Hooks into the helpdesk ticket creation to save program_type and ticket_club_id.

Since odoo_website_helpdesk is a third-party module with an unknown controller
base class, we use a post-create ORM hook on the model instead of overriding
the HTTP controller. This is safer and works regardless of which controller
the third-party module uses.

The actual saving happens in helpdesk_ticket.py via create() override.
This file provides a lightweight public JSON endpoint for form validation only.
"""
from odoo import http
from odoo.http import request


class HelpdeskProgramClubController(http.Controller):

    @http.route(
        "/helpdesk/validate_club",
        type="json",
        auth="public",
        csrf=False,
        website=True,
    )
    def validate_club(self, club_type=None, club_id=None, **kw):
        """
        Optional: called by JS before submit to verify the selected
        club_id actually belongs to the selected club_type.
        Returns {"valid": True/False, "name": "Club Name or error"}.
        """
        if not club_type or not club_id:
            return {"valid": False, "name": "Missing fields"}
        try:
            partner = (
                request.env["res.partner"]
                .sudo()
                .browse(int(club_id))
                .exists()
            )
            if partner and partner.club_type == club_type:
                return {"valid": True, "name": partner.name}
            return {"valid": False, "name": "Club does not match program type"}
        except Exception as e:
            return {"valid": False, "name": str(e)}
