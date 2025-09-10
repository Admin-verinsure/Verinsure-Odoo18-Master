from odoo import models, api

class ResPartner(models.Model):
    _inherit = "res.partner"   # fields already defined in rotary_project_map

    def _geo_address_line(self):
        self.ensure_one()
        parts = [
            self.street or "",
            self.street2 or "",
            self.city or "",
            self.state_id and self.state_id.name or "",
            self.zip or "",
            self.country_id and self.country_id.name or "",
        ]
        return ", ".join(p for p in parts if p).strip(", ")

    def action_locate_from_address(self):
        """Called by the button: geocode postal address -> write lat/lng."""
        for rec in self:
            addr = rec._geo_address_line()
            if not addr:
                continue
            coords = None
            if hasattr(rec, "geo_find"):
                coords = rec.geo_find(addr)
            elif hasattr(rec, "_geo_find"):
                coords = rec._geo_find(addr)
            if coords and len(coords) >= 2:
                rec.write({
                    "club_latitude": float(coords[0]),
                    "club_longitude": float(coords[1]),
                })
        return True

    @api.onchange("street", "street2", "city", "state_id", "zip", "country_id")
    def _onchange_autofill_coords(self):
        """Live fill while editing; persists when you Save."""
        for rec in self:
            addr = rec._geo_address_line()
            if not addr or not hasattr(rec, "geo_find"):
                continue
            coords = rec.geo_find(addr)
            if coords and len(coords) >= 2:
                rec.club_latitude  = float(coords[0])
                rec.club_longitude = float(coords[1])
