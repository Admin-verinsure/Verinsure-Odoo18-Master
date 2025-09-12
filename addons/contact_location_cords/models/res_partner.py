# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"  # club_latitude/club_longitude exist elsewhere

    # ------------------------
    # Config helpers
    # ------------------------
    def _lang_pref(self):
        ICP = self.env["ir.config_parameter"].sudo()
        lang = (ICP.get_param("base.geolocalize.language") or (self.env.user.lang or "en_US")).split("_")[0]
        return lang[:10]

    def _nominatim_base(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = ICP.get_param("base.geolocalize.nominatim.server") or "https://nominatim.openstreetmap.org"
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "your-app-name/1.0 (contact@example.com)"
        contact_email = ICP.get_param("base.geolocalize.contact_email") or "contact@example.com"
        return base_url.rstrip("/"), user_agent, contact_email

    # ------------------------
    # Address / Level helpers
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

    def _address_level(self):
        """
        empty  : no address parts at all
        country: only country
        state  : state (maybe +country), but no city/street/zip
        city   : city (maybe +state/country), but no street/zip
        street : has street or zip (most precise intent)
        """
        has_country = bool(self.country_id)
        has_state   = bool(self.state_id)
        has_city    = bool(self.city)
        has_street  = bool(self.street or self.street2)
        has_zip     = bool(self.zip)

        if not (has_country or has_state or has_city or has_street or has_zip):
            return "empty"
        if has_street or has_zip:
            return "street"
        if has_city:
            return "city"
        if has_state:
            return "state"
        # else only country
        return "country"

    # ------------------------
    # Precision & parsing
    # ------------------------
    def _coords_from_json(self, data, allow_coarse=False):
        """
        If allow_coarse=True, accept any result (country/state/city ok).
        Otherwise prefer street/house-level.
        """
        if isinstance(data, list) and data:
            r = data[0]
            if not allow_coarse:
                addresstype = (r.get("addresstype") or "").lower()
                rtype = (r.get("type") or "").lower()
                address = r.get("address") or {}
                # precise enough?
                if address.get("house_number"):
                    pass
                elif addresstype in {"house", "building", "address"} or rtype in {"house", "building"}:
                    pass
                elif addresstype in {"road", "street"} or rtype in {"road", "residential", "tertiary", "secondary", "primary", "trunk"}:
                    pass
                else:
                    try:
                        if int(r.get("place_rank") or 99) > 18:
                            return None  # reject locality-only if not allowing coarse
                    except Exception:
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

    def _geocode_via_nominatim(self, addr, allow_coarse=False):
        """
        Structured first; fallback to q=. allow_coarse controls precision gating.
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
            coords = self._coords_from_json(r.json(), allow_coarse=allow_coarse)
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
            return self._coords_from_json(r.json(), allow_coarse=allow_coarse)
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
                level = rec._address_level()
                if level == "empty":
                    rec.with_context(no_geocode=True).write({"club_latitude": 0.0, "club_longitude": 0.0})
                    continue
                addr = rec._geo_address_line()
                coords = rec._geocode_via_nominatim(addr, allow_coarse=(level in ("country","state","city")))
                if coords:
                    rec.with_context(no_geocode=True).write({"club_latitude": coords[0], "club_longitude": coords[1]})
                else:
                    # if we at least had some field but lookup failed, keep as-is (don't force 0.0)
                    pass
            except Exception as e:
                _logger.info("Geocode on create failed for %s: %s", rec.display_name, e)
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("no_geocode") or self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return res

        if any(k in vals for k in ADDR_FIELDS):
            for rec in self:
                try:
                    level = rec._address_level()
                    if level == "empty":
                        # Explicit request: when address empty -> 0.0
                        rec.with_context(no_geocode=True).write({"club_latitude": 0.0, "club_longitude": 0.0})
                        continue
                    addr = rec._geo_address_line()
                    coords = rec._geocode_via_nominatim(addr, allow_coarse=(level in ("country","state","city")))
                    if coords:
                        rec.with_context(no_geocode=True).write({"club_latitude": coords[0], "club_longitude": coords[1]})
                    # else: do nothing (keep previous coords) when lookup fails
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # Manual button (optional)
    def action_locate_from_address(self):
        for rec in self:
            level = rec._address_level()
            if level == "empty":
                rec.with_context(no_geocode=True).write({"club_latitude": 0.0, "club_longitude": 0.0})
                continue
            addr = rec._geo_address_line()
            coords = rec._geocode_via_nominatim(addr, allow_coarse=(level in ("country","state","city")))
            if coords:
                rec.with_context(no_geocode=True).write({"club_latitude": coords[0], "club_longitude": coords[1]})
        return True

    # Live fill in form (not persisted until Save)
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            level = rec._address_level()
            if level == "empty":
                rec.club_latitude = 0.0
                rec.club_longitude = 0.0
                continue
            addr = rec._geo_address_line()
            coords = rec._geocode_via_nominatim(addr, allow_coarse=(level in ("country","state","city")))
            if coords:
                rec.club_latitude, rec.club_longitude = coords
