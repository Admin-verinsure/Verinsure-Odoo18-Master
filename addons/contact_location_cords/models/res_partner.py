# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"  # club_latitude/club_longitude already exist elsewhere

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
    # Address builder (works even if street is empty)
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

    def _coords_from_json(self, data):
        if isinstance(data, list) and data:
            r = data[0]
            if not self._is_precise_enough(r):
                return None
            try:
                return float(r["lat"]), float(r.get("lon", r.get("lng")))
            except Exception:
                return None
        return None

    # ------------------------
    # Nominatim client
    # ------------------------
    def _nominatim_struct_params(self):
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

    def _geocode_via_nominatim(self, addr):
        """
        Structured search first; fallback to q=.
        Returns (lat, lon) or None.
        """
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {
            "User-Agent": user_agent,
            "Accept-Language": self._lang_pref(),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        # 1) structured
        sparams = self._nominatim_struct_params()
        sparams.setdefault("email", contact_email)
        try:
            _logger.debug("Nominatim structured: %s | %s", self.display_name, sparams)
            r = requests.get(f"{base_url}/search", params=sparams, headers=headers, timeout=12)
            r.raise_for_status()
            coords = self._coords_from_json(r.json())
            if coords:
                return coords
        except Exception as e:
            _logger.info("Structured geocode error for %s: %s", self.display_name, e)

        # 2) free-text q=
        cc = (self.country_id and (self.country_id.code or "")) or ""
        qparams = {"q": addr, "format": "jsonv2", "limit": 1, "addressdetails": 1, "email": contact_email}
        if cc:
            qparams["countrycodes"] = cc.lower()
        try:
            _logger.debug("Nominatim q=: %s | %s", self.display_name, qparams)
            r = requests.get(f"{base_url}/search", params=qparams, headers=headers, timeout=12)
            r.raise_for_status()
            return self._coords_from_json(r.json())
        except Exception as e:
            _logger.info("Free-text geocode error for %s: %s", self.display_name, e)
            return None

    # ------------------------
    # Server-side auto triggers
    # ------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return records
        for rec in records:
            try:
                addr = rec._geo_address_line()
                coords = rec._geocode_via_nominatim(addr)
                rec.with_context(no_geocode=True).write({
                    "club_latitude": coords and coords[0] or False,
                    "club_longitude": coords and coords[1] or False,
                })
            except Exception as e:
                _logger.info("Geocode on create failed for %s: %s", rec.display_name, e)
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("no_geocode") or self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return res

        # If ANY address field changed, recompute — even with empty street.
        if any(k in vals for k in ADDR_FIELDS):
            for rec in self:
                try:
                    addr = rec._geo_address_line()
                    _logger.debug("Geocode on write: %s | '%s'", rec.display_name, addr)
                    coords = rec._geocode_via_nominatim(addr)
                    # Always update: set new coords or clear if failed (so stale ones don't stick)
                    rec.with_context(no_geocode=True).write({
                        "club_latitude": coords and coords[0] or False,
                        "club_longitude": coords and coords[1] or False,
                    })
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # Manual button (optional on the form)
    def action_locate_from_address(self):
        for rec in self:
            addr = rec._geo_address_line()
            coords = rec._geocode_via_nominatim(addr)
            rec.with_context(no_geocode=True).write({
                "club_latitude": coords and coords[0] or False,
                "club_longitude": coords and coords[1] or False,
            })
        return True

    # Live fill in form (not persisted until Save)
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            addr = rec._geo_address_line()
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                rec.club_latitude, rec.club_longitude = coords
            else:
                rec.club_latitude = False
                rec.club_longitude = False
