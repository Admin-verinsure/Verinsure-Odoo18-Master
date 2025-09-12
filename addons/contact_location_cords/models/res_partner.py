# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"

    # Invisible trigger that runs on form open (compute executes on read)
    x_auto_geocode = fields.Boolean(
        string="Auto Geocode Trigger",
        compute="_compute_auto_geocode",
        store=False,
    )

    # ------------------------
    # Helpers
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
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "mytest-geocode/1.0 (test)"
        contact_email = (ICP.get_param("base.geolocalize.contact_email") or "").strip()
        if contact_email and "@" not in contact_email:
            contact_email = ""
        return base_url, user_agent, contact_email

    def _parse_nominatim_resp(self, data):
        if isinstance(data, list) and data:
            d0 = data[0]
            try:
                return float(d0.get("lat")), float(d0.get("lon", d0.get("lng")))
            except Exception:
                return None
        return None

    def _geocode_via_nominatim(self, addr, cc_lower=None):
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent}

        # 1) structured
        sparams = self._nominatim_structured_params()
        if contact_email:
            sparams["email"] = contact_email
        try:
            r = requests.get(f"{base_url}/search", params=sparams, headers=headers, timeout=12)
            r.raise_for_status()
            coords = self._parse_nominatim_resp(r.json())
            if coords:
                return coords
        except Exception as e:
            _logger.info("Nominatim structured error for %s: %s", self.display_name, e)

        # 2) q= fallback
        qparams = {"q": addr, "format": "jsonv2", "limit": 1, "addressdetails": 1}
        if cc_lower:
            qparams["countrycodes"] = cc_lower
        if contact_email:
            qparams["email"] = contact_email
        try:
            r = requests.get(f"{base_url}/search", params=qparams, headers=headers, timeout=12)
            r.raise_for_status()
            return self._parse_nominatim_resp(r.json())
        except Exception as e:
            _logger.info("Nominatim q= error for %s: %s", self.display_name, e)
            return None

    def _write_coords_builtin(self, coords):
        if not coords:
            return
        for rec in self:
            rec.with_context(no_geocode=True).write({
                "partner_latitude":  coords[0],
                "partner_longitude": coords[1],
            })

    # ------------------------
    # Auto on create/write (keeps things in sync when you edit)
    # ------------------------
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return recs
        for rec in recs:
            try:
                addr = rec._geo_address_line()
                if not addr:
                    continue
                coords = rec._geocode_via_nominatim(addr)
                if coords:
                    rec._write_coords_builtin(coords)
            except Exception as e:
                _logger.info("Geocode on create failed for %s: %s", rec.display_name, e)
        return recs

    def write(self, vals):
        address_changed = any(k in vals for k in ADDR_FIELDS)
        res = super().write(vals)
        if address_changed and not (self.env.context.get("no_geocode") or self.env.context.get("install_mode") or self.env.context.get("disable_geocode")):
            for rec in self:
                try:
                    addr = rec._geo_address_line()
                    if not addr:
                        continue
                    coords = rec._geocode_via_nominatim(addr)
                    if coords:
                        rec._write_coords_builtin(coords)
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # ------------------------
    # Manual button (Option A)
    # ------------------------
    def action_locate_from_address(self):
        """Button: geocode current postal address and write coords (built-in fields)."""
        for rec in self:
            try:
                addr = rec._geo_address_line()
            except Exception:
                addr = ""
            if not addr:
                continue

            coords = None
            # Prefer your Nominatim helper
            try:
                coords = rec._geocode_via_nominatim(addr)
            except Exception:
                coords = None

            # Fallback to Odoo's base_geolocalize if available
            if not coords:
                if hasattr(rec, "geo_find"):
                    try:
                        coords = rec.geo_find(addr)
                    except Exception:
                        coords = None
                elif hasattr(rec, "_geo_find"):
                    try:
                        coords = rec._geo_find(addr)
                    except Exception:
                        coords = None

            if coords and len(coords) >= 2:
                rec.with_context(no_geocode=True).write({
                    "partner_latitude":  float(coords[0]),
                    "partner_longitude": float(coords[1]),
                })
        return True

    # ------------------------
    # The on-open trigger (compute runs when field is in the view)
    # ------------------------
    @api.depends(*ADDR_FIELDS, "partner_latitude", "partner_longitude")
    def _compute_auto_geocode(self):
        """
        Compute executes when the form loads this field.
        If address exists and coords are empty/zero, geocode once and write.
        """
        blocked = self.env.context.get("install_mode") or self.env.context.get("no_geocode") or self.env.context.get("disable_geocode")
        for rec in self:
            try:
                if blocked:
                    rec.x_auto_geocode = False
                    continue

                has_addr = bool(rec.country_id or rec.state_id or rec.city or rec.street or rec.street2 or rec.zip)
                lat_missing = (not rec.partner_latitude) or abs(rec.partner_latitude) < 1e-12
                lng_missing = (not rec.partner_longitude) or abs(rec.partner_longitude) < 1e-12
                if has_addr and (lat_missing or lng_missing):
                    addr = rec._geo_address_line()
                    if addr:
                        coords = rec._geocode_via_nominatim(addr)
                        if not coords and hasattr(rec, "geo_find"):
                            try:
                                coords = rec.geo_find(addr)
                            except Exception:
                                coords = None
                        if coords:
                            rec.with_context(no_geocode=True).write({
                                "partner_latitude":  coords[0],
                                "partner_longitude": coords[1],
                            })
                rec.x_auto_geocode = True  # mark computed (value not used)
            except Exception as e:
                _logger.info("Auto geocode on form open skipped for %s: %s", rec.display_name, e)
                rec.x_auto_geocode = False
