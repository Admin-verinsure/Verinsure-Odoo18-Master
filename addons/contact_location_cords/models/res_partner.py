# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"  # fields already defined elsewhere

    def _geo_address_line(self):
        self.ensure_one()
        parts = [
            self.street or "",
            self.street2 or "",
            self.city or "",
            (self.state_id and self.state_id.name) or "",
            self.zip or "",
            (self.country_id and self.country_id.name) or "",
        ]
        return ", ".join(p for p in parts if p).strip(", ")

    # --- NEW: structured params builder for Nominatim ---
    def _nominatim_structured_params(self):
        self.ensure_one()
        street_line = ", ".join([p for p in [self.street or "", self.street2 or ""] if p]).strip(", ")
        params = {
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }
        if street_line:
            params["street"] = street_line
        if self.city:
            params["city"] = self.city
        if self.state_id and self.state_id.name:
            params["state"] = self.state_id.name
        if self.zip:
            params["postalcode"] = self.zip
        if self.country_id and (self.country_id.name or self.country_id.code):
            # Both help: free-text country & ISO2 countrycodes for bias
            params["country"] = self.country_id.name or ""
            params["countrycodes"] = (self.country_id.code or "").lower()
        return params

    def _nominatim_base(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = ICP.get_param("base.geolocalize.nominatim.server") or "https://nominatim.openstreetmap.org"
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "your-app-name/1.0 (contact@example.com)"
        contact_email = ICP.get_param("base.geolocalize.contact_email") or "contact@example.com"
        return base_url.rstrip("/"), user_agent, contact_email

    def _parse_nominatim_resp(self, data):
        if isinstance(data, list) and data:
            d0 = data[0]
            try:
                lat = float(d0.get("lat"))
                lon = float(d0.get("lon", d0.get("lng")))
                # (0,0) is valid but unlikely for postal addresses; accept any floats returned
                return (lat, lon)
            except Exception:
                return None
        return None

    def _geocode_via_nominatim(self, addr):
        """Try structured search first; fall back to free-text q=."""
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()

        # --- Attempt 1: structured search ---
        sparams = self._nominatim_structured_params()
        try:
            resp = requests.get(
                f"{base_url}/search",
                params=sparams,
                headers={"User-Agent": user_agent},
                timeout=12,
            )
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if coords:
                return coords
            _logger.info("Nominatim structured miss for %s (params=%s)", self.display_name, sparams)
        except Exception as e:
            _logger.warning("Nominatim structured search error for %s: %s", self.display_name, e)

        # --- Attempt 2: fallback to free-text q= (your original) ---
        cc = (self.country_id and (self.country_id.code or "")) or ""
        qparams = {
            "q": addr,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }
        if cc:
            qparams["countrycodes"] = cc.lower()
        # (Optional but recommended by Nominatim policy)
        qparams["email"] = contact_email

        try:
            resp = requests.get(
                f"{base_url}/search",
                params=qparams,
                headers={"User-Agent": user_agent},
                timeout=12,
            )
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if not coords:
                _logger.info("Nominatim free-text miss for %s (q=%s)", self.display_name, addr)
            return coords
        except Exception as e:
            _logger.error("Nominatim free-text search error for %s: %s", self.display_name, e)
            return None

    def action_locate_from_address(self):
        """Button: geocode postal address and WRITE coords."""
        for rec in self:
            coords = rec._geocode_via_nominatim(rec._geo_address_line())
            if coords:
                rec.write({"club_latitude": coords[0], "club_longitude": coords[1]})
        return True

    @api.onchange("street", "street2", "city", "state_id", "zip", "country_id")
    def _onchange_autofill_coords(self):
        """While editing: fill fields in the form (persist on Save)."""
        for rec in self:
            coords = rec._geocode_via_nominatim(rec._geo_address_line())
            if coords:
                rec.club_latitude = coords[0]
                rec.club_longitude = coords[1]
