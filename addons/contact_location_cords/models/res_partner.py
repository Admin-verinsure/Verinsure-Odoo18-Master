# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

ADDRESS_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"   # fields already defined in rotary_project_map

    # ------------------------
    # Config helpers
    # ------------------------
    def _lang_pref(self):
        ICP = self.env["ir.config_parameter"].sudo()
        lang = (ICP.get_param("base.geolocalize.language") or (self.env.user.lang or "en_US")).split("_")[0]
        return lang[:10]

    def _strict_precision(self):
        ICP = self.env["ir.config_parameter"].sudo()
        v = (ICP.get_param("geocode.nominatim.strict_precision") or "0").strip()
        return v not in ("0", "false", "False", "no", "No")

    def _nominatim_base(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = ICP.get_param("base.geolocalize.nominatim.server") or "https://nominatim.openstreetmap.org"
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "your-app-name/1.0 (contact@example.com)"
        contact_email = ICP.get_param("base.geolocalize.contact_email") or "contact@example.com"
        return base_url.rstrip("/"), user_agent, contact_email

    # ------------------------
    # Address assembly
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
    # Precision & parsing
    # ------------------------
    def _is_precise_enough(self, result):
        if not result:
            return False
        strict = self._strict_precision()
        addresstype = (result.get("addresstype") or "").lower()
        rtype = (result.get("type") or "").lower()
        address = result.get("address") or {}
        if address.get("house_number"):
            return True
        if addresstype in {"house", "building", "address"} or rtype in {"house", "building"}:
            return True
        if addresstype in {"road", "street"} or rtype in {"road", "residential", "tertiary", "secondary", "primary", "trunk"}:
            return True
        try:
            return int(result.get("place_rank") or 99) <= 18
        except Exception:
            return not strict

    def _parse_nominatim_resp(self, data):
        if isinstance(data, list) and data:
            d0 = data[0]
            if not self._is_precise_enough(d0):
                return None
            try:
                lat = float(d0.get("lat"))
                lon = float(d0.get("lon", d0.get("lng")))
                return (lat, lon)
            except Exception:
                return None
        return None

    # ------------------------
    # Nominatim request params
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

    # ------------------------
    # Geocoder (Nominatim only)
    # ------------------------
    def _geocode_via_nominatim(self, addr):
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {
            "User-Agent": user_agent,
            "Accept-Language": self._lang_pref(),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        # 1) Structured
        sparams = self._nominatim_structured_params()
        sparams.setdefault("email", contact_email)
        try:
            _logger.debug("Nominatim structured addr=%s params=%s", addr, sparams)
            resp = requests.get(f"{base_url}/search", params=sparams, headers=headers, timeout=12)
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if coords:
                return coords
            _logger.info("Structured miss for %s", self.display_name)
        except Exception as e:
            _logger.warning("Structured search error for %s: %s", self.display_name, e)

        # 2) Fallback: q=
        cc = (self.country_id and (self.country_id.code or "")) or ""
        qparams = {"q": addr, "format": "jsonv2", "limit": 1, "addressdetails": 1, "email": contact_email}
        if cc:
            qparams["countrycodes"] = cc.lower()
        try:
            _logger.debug("Nominatim q= addr=%s params=%s", addr, qparams)
            resp = requests.get(f"{base_url}/search", params=qparams, headers=headers, timeout=12)
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if not coords:
                _logger.info("q= miss for %s", self.display_name)
            return coords
        except Exception as e:
            _logger.error("Free-text search error for %s: %s", self.display_name, e)
            return None

    # ------------------------
    # Triggers
    # ------------------------
    def _geocode_if_ready(self, clear_on_fail=False):
        """
        Recompute coords when address looks complete.
        clear_on_fail=True will blank stale coords if lookup fails.
        """
        if self.env.context.get("install_mode") or self.env.context.get("no_geocode") or self.env.context.get("disable_geocode"):
            return False

        for rec in self:
            if not ((rec.street or rec.street2) and (rec.city or rec.zip or rec.state_id) and rec.country_id):
                continue
            addr = rec._geo_address_line()
            _logger.debug("Geocode try: %s | '%s'", rec.display_name, addr)
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                rec.with_context(no_geocode=True).write({"club_latitude": coords[0], "club_longitude": coords[1]})
                _logger.debug("Geocode OK: %s -> %s", rec.display_name, coords)
            elif clear_on_fail and (rec.club_latitude or rec.club_longitude):
                rec.with_context(no_geocode=True).write({"club_latitude": False, "club_longitude": False})
                _logger.info("Geocode failed, cleared stale coords: %s", rec.display_name)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            records._geocode_if_ready(clear_on_fail=False)
        except Exception as e:
            _logger.info("Geocode on create skipped/failed: %s", e)
        return records

    def write(self, vals):
        address_changed = any(k in vals for k in ADDRESS_FIELDS)
        res = super().write(vals)
        if address_changed:
            try:
                # Force a recompute and clear stale coords if lookup fails
                self._geocode_if_ready(clear_on_fail=True)
            except Exception as e:
                _logger.info("Geocode on write skipped/failed: %s", e)
        return res

    # Manual button still works if you have it on the form
    def action_locate_from_address(self):
        for rec in self:
            rec.with_context(no_geocode=False)._geocode_if_ready(clear_on_fail=False)
        return True

    @api.onchange(*ADDRESS_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            if not ((rec.street or rec.street2) and (rec.city or rec.zip or rec.state_id) and rec.country_id):
                continue
            addr = rec._geo_address_line()
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                rec.club_latitude, rec.club_longitude = coords
