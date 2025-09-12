# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Invisible non-stored trigger; safe to keep (auto-fills on open if empty)
    x_auto_geocode = fields.Boolean(
        string="Auto Geocode Trigger",
        compute="_compute_auto_geocode",
        store=False,
    )

    # ---------------------------------------------------------------------
    # Address helpers
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # Nominatim client
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # WRITE HELPERS: write to *both* built-ins and club_* when available
    # ---------------------------------------------------------------------
    def _write_coords_all(self, coords):
        """Write to partner_* and (if present) to club_* so both tabs show values."""
        if not coords:
            return
        F = self._fields
        vals = {}
        # built-ins (base_geolocalize)
        if "partner_latitude" in F:
            vals["partner_latitude"] = coords[0]
        if "partner_longitude" in F:
            vals["partner_longitude"] = coords[1]
        # rotary_project_map custom fields (Rotary Org Info tab)
        if "club_latitude" in F:
            vals["club_latitude"] = coords[0]
        if "club_longitude" in F:
            vals["club_longitude"] = coords[1]
        if vals:
            self.with_context(no_geocode=True).write(vals)

    # ---------------------------------------------------------------------
    # Manual button (kept for user control)
    # ---------------------------------------------------------------------
    def action_locate_from_address(self):
        """Button: geocode current postal address and write coords to all fields."""
        for rec in self:
            addr = rec._geo_address_line() if hasattr(rec, "_geo_address_line") else ""
            if not addr:
                continue
            coords = None
            try:
                coords = rec._geocode_via_nominatim(addr)
            except Exception:
                coords = None
            if not coords and hasattr(rec, "geo_find"):
                try:
                    coords = rec.geo_find(addr)
                except Exception:
                    coords = None
            if coords and len(coords) >= 2:
                rec._write_coords_all((float(coords[0]), float(coords[1])))
        return True

    # ---------------------------------------------------------------------
    # Auto on create/write (never blank on failure)
    # ---------------------------------------------------------------------
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
                    rec._write_coords_all(coords)
            except Exception as e:
                _logger.info("Geocode on create failed for %s: %s", rec.display_name, e)
        return recs

    def write(self, vals):
        address_changed = any(k in vals for k in ADDR_FIELDS)

        # snapshot previous coords to avoid ending up with 0.0 on failure
        prev = {}
        if address_changed:
            for rec in self:
                prev[rec.id] = {
                    "plat": getattr(rec, "partner_latitude", False),
                    "plng": getattr(rec, "partner_longitude", False),
                    "clat": getattr(rec, "club_latitude", False) if "club_latitude" in rec._fields else False,
                    "clng": getattr(rec, "club_longitude", False) if "club_longitude" in rec._fields else False,
                }

        res = super().write(vals)

        if address_changed and not (self.env.context.get("no_geocode") or self.env.context.get("install_mode") or self.env.context.get("disable_geocode")):
            for rec in self:
                try:
                    addr = rec._geo_address_line()
                    if not addr:
                        continue
                    coords = rec._geocode_via_nominatim(addr)
                    if coords:
                        rec._write_coords_all(coords)
                    else:
                        # restore previous coords (avoid 0.0 if lookup failed)
                        old = prev.get(rec.id) or {}
                        restore = {}
                        if "partner_latitude" in rec._fields and old.get("plat") is not None:
                            restore["partner_latitude"] = old["plat"]
                        if "partner_longitude" in rec._fields and old.get("plng") is not None:
                            restore["partner_longitude"] = old["plng"]
                        if "club_latitude" in rec._fields and old.get("clat") is not None:
                            restore["club_latitude"] = old["clat"]
                        if "club_longitude" in rec._fields and old.get("clng") is not None:
                            restore["club_longitude"] = old["clng"]
                        if restore:
                            rec.with_context(no_geocode=True).write(restore)
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # ---------------------------------------------------------------------
    # Auto on form open (fills once if empty)
    # ---------------------------------------------------------------------
    @api.depends(*ADDR_FIELDS, "partner_latitude", "partner_longitude")
    def _compute_auto_geocode(self):
        blocked = (self.env.context.get("install_mode") or
                   self.env.context.get("no_geocode") or
                   self.env.context.get("disable_geocode"))
        for rec in self:
            try:
                if blocked:
                    rec.x_auto_geocode = False
                    continue

                has_addr = bool(rec.country_id or rec.state_id or rec.city or rec.street or rec.street2 or rec.zip)

                # treat as missing if partner_* are empty/zero
                lat_missing = (not getattr(rec, "partner_latitude", False)) or abs(getattr(rec, "partner_latitude", 0.0)) < 1e-12
                lng_missing = (not getattr(rec, "partner_longitude", False)) or abs(getattr(rec, "partner_longitude", 0.0)) < 1e-12

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
                            rec._write_coords_all(coords)
                rec.x_auto_geocode = True
            except Exception as e:
                _logger.info("Auto geocode on form open skipped for %s: %s", rec.display_name, e)
                rec.x_auto_geocode = False

    # ---------------------------------------------------------------------
    # Onchange (form preview) — set both pairs in the form cache if found
    # ---------------------------------------------------------------------
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            addr = rec._geo_address_line()
            if not addr:
                continue
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                if "partner_latitude" in rec._fields:
                    rec.partner_latitude = coords[0]
                if "partner_longitude" in rec._fields:
                    rec.partner_longitude = coords[1]
                if "club_latitude" in rec._fields:
                    rec.club_latitude = coords[0]
                if "club_longitude" in rec._fields:
                    rec.club_longitude = coords[1]
            # else: leave current values visible; do not zero them
