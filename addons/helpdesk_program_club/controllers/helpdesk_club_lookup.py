# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class HelpdeskClubLookup(http.Controller):
    """
    Two public JSON endpoints used by the frontend JS:

      POST /helpdesk/program_types
        → returns [{"key": "rotary", "label": "Rotary"}, …]
          (the same selection pairs as res.partner.club_type)

      POST /helpdesk/clubs_by_program
        → params: { club_type: "rotary" }
        → returns [{"id": 42, "name": "Rotary Club XYZ"}, …]
    """

    # ------------------------------------------------------------------
    # Endpoint 1 – Program Type list (drives the first dropdown)
    # ------------------------------------------------------------------
    @http.route(
        "/helpdesk/program_types",
        type="json",
        auth="public",
        csrf=False,
        website=True,
    )
    def helpdesk_program_types(self, **kw):
        field = request.env["res.partner"]._fields.get("club_type")
        if not field:
            return []
        sel = field.selection
        if callable(sel):
            sel = sel(request.env["res.partner"])
        return [{"key": k, "label": v} for k, v in (sel or [])]

    # ------------------------------------------------------------------
    # Endpoint 2 – Club list filtered by selected Program Type
    # ------------------------------------------------------------------
    @http.route(
        "/helpdesk/clubs_by_program",
        type="json",
        auth="public",
        csrf=False,
        website=True,
    )
    def helpdesk_clubs_by_program(self, club_type=None, search="", **kw):
        if not club_type:
            return []

        domain = [
            ("club_type", "=", club_type),
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
