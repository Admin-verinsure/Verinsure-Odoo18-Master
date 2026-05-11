# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class HelpdeskClubLookup(http.Controller):
    """
    Standalone JSON endpoints — no dependency on signup_club_type.

      POST /helpdesk/program_types
        → [{"id": 1, "name": "Rotary"}, …]  from helpdesk.program.type

      POST /helpdesk/clubs_by_program
        → params: { program_type_id: 1 }
        → [{"id": 42, "name": "Rotary Club XYZ"}, …]  from res.partner
    """

    @http.route(
        "/helpdesk/program_types",
        type="json",
        auth="public",
        csrf=False,
        website=True,
    )
    def helpdesk_program_types(self, **kw):
        types = request.env["helpdesk.program.type"].sudo().search_read(
            [("active", "=", True)],
            ["id", "name"],
            order="name",
        )
        return types  # [{id, name}, …]

    @http.route(
        "/helpdesk/clubs_by_program",
        type="json",
        auth="public",
        csrf=False,
        website=True,
    )
    def helpdesk_clubs_by_program(self, program_type_id=None, search="", **kw):
        if not program_type_id:
            return []
        try:
            pt_id = int(program_type_id)
        except (TypeError, ValueError):
            return []

        domain = [
            ("helpdesk_program_type_id", "=", pt_id),
            ("active", "=", True),
        ]
        if search and search.strip():
            domain.append(("name", "ilike", search.strip()))

        partners = request.env["res.partner"].sudo().search_read(
            domain,
            ["id", "name"],
            order="name",
            limit=100,
        )
        return partners
