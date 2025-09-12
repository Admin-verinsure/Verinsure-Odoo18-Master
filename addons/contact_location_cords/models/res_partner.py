# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------
    # Address helpers
    # ------------------------
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

    # ------------------------
    # Nominatim client (simple & reliable)
    # ------------------------
    def _nominatim_structured_params(self):
        self.ensure_one()
        street_line = ", ".join([p for p in [self.street or "", self.street2 or ""] if p]).strip(", ")
        params = {"format": "jsonv2", "limit": 1, "addressdetails": 1}
        if street_line:
            params["street"] = street_line
        if self.city:
            params["city"] = self.city
        if self.state_id and self.state_id.name:
            params["state"] = self.state_id.name
        if self.zip:
            params["postalcode"] = self.zip
        if self.country_id and (self.country_id.name or self.country_id.code):
            params["country"] = self.country_id.name or ""
            params["countrycodes"] = (self.country_id.code or "").lower()
        return params

    def _nominatim_base(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (ICP.get_param("base.geolocalize.nominatim.server") or
                    "https://nominatim.openstreetmap.org").rstrip("/")
        # keep it loose for testing; set your own UA via system params if you want
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "mytest-geocode/1.0 (test)"
        contact_email = (ICP.get_param("base.geolocalize.contact_email") or "").strip()
        if contact_email and "@" not in contact_email:
            contact_email = ""
        return base_url, user_agent, contact_email

    def _parse_nominatim_resp(self, data):
        if isinstance(data, list) and data:
            d0 = data[0]
            try:
                lat = float(d0.get("lat"))
                lon = float(d0.get("lon", d0.get("lng")))
                return (lat, lon)
            except Exception:
                return None
        return None

    def _geocode_via_nominatim(self, addr):
        """Structured first; fallback to q=. Returns (lat, lon) or None."""
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent}

        # 1) structured
        sparams = self._nominatim_structured_params()
        if contact_email:
            sparams["email"] = contact_email
        try:
            resp = requests.get(f"{base_url}/search", params=sparams, headers=headers, timeout=12)
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if coords:
                return coords
            _logger.info("Nominatim structured miss for %s", self.display_name)
        except Exception as e:
            _logger.info("Nominatim structured error for %s: %s", self.display_name, e)

        # 2) q= fallback
        cc = (self.country_id and (self.country_id.code or "")) or ""
        qparams = {"q": addr, "format": "jsonv2", "limit": 1, "addressdetails": 1}
        if cc:
            qparams["countrycodes"] = cc.lower()
        if contact_email:
            qparams["email"] = contact_email
        try:
            resp = requests.get(f"{base_url}/search", params=qparams, headers=headers, timeout=12)
            resp.raise_for_status()
            return self._parse_nominatim_resp(resp.json())
        except Exception as e:
            _logger.info("Nominatim q= error for %s: %s", self.display_name, e)
            return None

    # ------------------------
    # Writing helpers (built-ins only)
    # ------------------------
    def _write_coords_builtin(self, coords):
        """Write only on success to partner_latitude/partner_longitude."""
        if not coords:
            return
        for rec in self:
            rec.with_context(no_geocode=True).write({
                "partner_latitude":  coords[0],
                "partner_longitude": coords[1],
            })

    # ------------------------
    # Auto hooks
    # ------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # skip during installs/imports
        if self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return records
        for rec in records:
            try:
                addr = rec._geo_address_line()
                if not addr:
                    continue
                coords = rec._geocode_via_nominatim(addr)
                if coords:
                    rec._write_coords_builtin(coords)
            except Exception as e:
                _logger.info("Geocode on create failed for %s: %s", rec.display_name, e)
        return records

    def write(self, vals):
        address_changed = any(k in vals for k in ADDR_FIELDS)
        res = super().write(vals)
        if address_changed and not (self.env.context.get("no_geocode") or self.env.context.get("install_mode") or self.env.context.get("disable_geocode")):
            for rec in self:
                try:
                    addr = rec._geo_address_line()
                    if not addr:
                        # do not force 0.0; just keep whatever was there
                        continue
                    coords = rec._geocode_via_nominatim(addr)
                    if coords:
                        rec._write_coords_builtin(coords)
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # Optional manual button
    def action_locate_from_address(self):
        for rec in self:
            addr = rec._geo_address_line()
            if not addr:
                continue
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                rec._write_coords_builtin(coords)
        return True

    # Onchange (form preview only; persists when you Save)
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            addr = rec._geo_address_line()
            if not addr:
                continue
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                rec.partner_latitude, rec.partner_longitude = coords
