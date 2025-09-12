# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------
    # Helpers
    # ------------------------
    def _geo_address_line_vals(self, vals):
        """Build one-line address from a dict of values (not from record)."""
        self.ensure_one()
        # state_id / country_id are ids here
        state_name = ""
        if vals.get("state_id"):
            state_name = self.env["res.country.state"].browse(vals["state_id"]).name or ""
        country_name = ""
        country_code = ""
        if vals.get("country_id"):
            c = self.env["res.country"].browse(vals["country_id"])
            country_name = c.name or ""
            country_code = (c.code or "").lower()
        parts = [
            vals.get("street") or "",
            vals.get("street2") or "",
            vals.get("city") or "",
            state_name,
            vals.get("zip") or "",
            country_name,
        ]
        line = ", ".join(p for p in parts if p).strip(", ")
        return line, country_code

    def _geo_address_line(self):
        """Address line from record (used in create/write/button paths)."""
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

    def _geocode_via_nominatim(self, addr, cc_lower=None):
        """Structured first; fallback to q=. Returns (lat, lon) or None."""
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent}

        # structured
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

        # q= fallback, optionally bias by country code
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
        """Write only on success to partner_latitude/partner_longitude."""
        if not coords:
            return
        for rec in self:
            rec.with_context(no_geocode=True).write({
                "partner_latitude":  coords[0],
                "partner_longitude": coords[1],
            })

    # ------------------------
    # AUTO on create / write (already had)
    # ------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
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
                        continue
                    coords = rec._geocode_via_nominatim(addr)
                    if coords:
                        rec._write_coords_builtin(coords)
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # ------------------------
    # NEW: AUTO on form open (read-time fill once)
    # ------------------------
    def read(self, fields=None, load="_classic_read"):
        """
        When opening a single partner in a form, if partner_latitude/longitude
        are empty but we have an address, geocode once and write before returning.
        Guarded to avoid loops and list view mass calls.
        """
        # Skip in special contexts and for multi-record reads
        if (not self.env.context.get("no_geocode") and
            not self.env.context.get("install_mode") and
            len(self.ids) == 1):
            try:
                # First get current values WITHOUT triggering this hook again
                vals = self.with_context(no_geocode=True).read([
                    "partner_latitude", "partner_longitude",
                    "street", "street2", "city", "state_id", "zip", "country_id"
                ])[0]

                need_lat = not vals.get("partner_latitude")
                need_lng = not vals.get("partner_longitude")
                has_any_addr = any(vals.get(k) for k in ("street", "street2", "city", "state_id", "zip", "country_id"))

                if (need_lat or need_lng) and has_any_addr:
                    # Build address string from vals (not from fields to avoid recursion)
                    addr, cc = self._geo_address_line_vals(vals)
                    coords = None
                    if addr:
                        # We call VIA self (record) so structured params also work
                        coords = self._geocode_via_nominatim(addr, cc_lower=cc)

                    if coords:
                        # Write and also inject into the 'result' we will return
                        self.with_context(no_geocode=True).write({
                            "partner_latitude":  coords[0],
                            "partner_longitude": coords[1],
                        })
                        # Fall through; we will re-read below via super()
            except Exception as e:
                _logger.info("Auto geocode on read skipped: %s", e)

        # Return the (possibly updated) values
        return super().read(fields=fields, load=load)

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

    # Onchange: preview only
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            addr = rec._geo_address_line()
            if not addr:
                continue
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                rec.partner_latitude, rec.partner_longitude = coords
