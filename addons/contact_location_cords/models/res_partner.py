# -*- coding: utf-8 -*-
import requests
from odoo import models, api

class ResPartner(models.Model):
    _inherit = "res.partner"  # fields already defined elsewhere

    # Build a one-line address
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

    def _geocode_via_nominatim(self, addr):
        """Call Nominatim directly (works without API key). Returns (lat, lon) or None."""
        if not addr:
            return None
        ICP = self.env["ir.config_parameter"].sudo()
        # Allow override via config; else default to official server
        base_url = ICP.get_param("base.geolocalize.nominatim.server") or "https://nominatim.openstreetmap.org"
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "not4profit.online-contact-geocode/1.0"

        # Bias by country if we have it (2-letter code)
        cc = (self.country_id and self.country_id.code or "") or ""
        params = {
            "q": addr,
            "format": "json",
            "limit": 1,
            "addressdetails": 0,
        }
        if cc:
            params["countrycodes"] = cc.lower()

        try:
            resp = requests.get(
                f"{base_url.rstrip('/')}/search",
                params=params,
                headers={"User-Agent": user_agent},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                d0 = data[0]
                # Nominatim uses 'lon' (not 'lng')
                lat = float(d0.get("lat", 0.0))
                lon = float(d0.get("lon", d0.get("lng", 0.0)))
                if lat and lon:
                    return (lat, lon)
        except Exception:
            # swallow and return None; you can log if you want
            return None
        return None

    def action_locate_from_address(self):
        """Button: geocode postal address and WRITE coords."""
        for rec in self:
            coords = rec._geocode_via_nominatim(rec._geo_address_line())
            if coords:
                rec.write({"club_latitude": coords[0], "club_longitude": coords[1]})
        # Optional toast (uncomment to show a popup):
        # return {"type": "ir.actions.client", "tag": "display_notification",
        #         "params": {"title": "Geocode", "message": "Done", "sticky": False}}
        return True

    @api.onchange("street", "street2", "city", "state_id", "zip", "country_id")
    def _onchange_autofill_coords(self):
        """While editing: fill fields in the form (persist on Save)."""
        for rec in self:
            coords = rec._geocode_via_nominatim(rec._geo_address_line())
            if coords:
                rec.club_latitude = coords[0]
                rec.club_longitude = coords[1]
