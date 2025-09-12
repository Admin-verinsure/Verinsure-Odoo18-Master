# -*- coding: utf-8 -*-
import logging
import requests
import hashlib
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

ADDRESS_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")

class ResPartner(models.Model):
    _inherit = "res.partner"  # fields already defined elsewhere

    # Stores the last geocoded signature to avoid re-calling when address is unchanged
    club_geo_sig = fields.Char(string="Geo Signature", copy=False, index=True)

    # ------------------------
    # Helpers / config
    # ------------------------
    def _lang_pref(self):
        """Preferred language for Nominatim."""
        ICP = self.env["ir.config_parameter"].sudo()
        lang = (ICP.get_param("base.geolocalize.language") or (self.env.user.lang or "en_US")).split("_")[0]
        return lang[:10]

    def _strict_precision(self):
        """
        If True (1), only accept house/street-level results.
        System Parameter: geocode.nominatim.strict_precision (default: 0 = allow coarse fallbacks)
        """
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
    # Address + signature
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

    def _address_signature(self):
        """Stable hash of the address fields used for geocoding."""
        self.ensure_one()
        raw = [
            self.street or "",
            self.street2 or "",
            self.city or "",
            (self.state_id and self.state_id.name) or "",
            self.zip or "",
            (self.country_id and self.country_id.code) or (self.country_id and self.country_id.name) or "",
        ]
        s = "|".join(raw)
        return hashlib.sha1(s.encode("utf-8")).hexdigest()

    # ------------------------
    # Precision handling
    # ------------------------
    def _is_precise_enough(self, result):
        """
        Accept house/building/road-level; reject city/ZIP unless strict off.
        """
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
        """Return (lat, lon) or None after precision gate."""
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

    # --- Structured params builder for Nominatim ---
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
    # Main geocoder
    # ------------------------
    def _geocode_via_nominatim(self, addr):
        """Try structured search first; fall back to free-text q=."""
        if not addr:
            return None
        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent, "Accept-Language": self._lang_pref()}

        # Attempt 1: structured
        sparams = self._nominatim_structured_params()
        sparams.setdefault("email", contact_email)
        try:
            resp = requests.get(f"{base_url}/search", params=sparams, headers=headers, timeout=12)
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if coords:
                return coords
            _logger.info("Nominatim structured miss for %s (params=%s)", self.display_name, sparams)
        except Exception as e:
            _logger.warning("Nominatim structured error for %s: %s", self.display_name, e)

        # Attempt 2: free-text q=
        cc = (self.country_id and (self.country_id.code or "")) or ""
        qparams = {"q": addr, "format": "jsonv2", "limit": 1, "addressdetails": 1, "email": contact_email}
        if cc:
            qparams["countrycodes"] = cc.lower()
        try:
            resp = requests.get(f"{base_url}/search", params=qparams, headers=headers, timeout=12)
            resp.raise_for_status()
            coords = self._parse_nominatim_resp(resp.json())
            if not coords:
                _logger.info("Nominatim free-text miss for %s (q=%s)", self.display_name, addr)
            return coords
        except Exception as e:
            _logger.error("Nominatim free-text error for %s: %s", self.display_name, e)
            return None

    # ------------------------
    # Orchestrators
    # ------------------------
    def _geocode_if_needed(self, force=False):
        """
        Compute coords if address signature changed or if forced.
        Skips during installs/imports if context disables it.
        """
        if self.env.context.get("no_geocode") or self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return False

        for rec in self:
            # minimal completeness: some street OR street2, some locality, and country
            if not ((rec.street or rec.street2) and (rec.city or rec.zip or rec.state_id) and rec.country_id):
                continue

            sig = rec._address_signature()
            if not force and rec.club_geo_sig and rec.club_geo_sig == sig and rec.club_latitude and rec.club_longitude:
                continue  # nothing changed

            addr = rec._geo_address_line()
            coords = rec._geocode_via_nominatim(addr)
            if coords:
                # avoid recursion by disabling geocode in context
                rec.with_context(no_geocode=True).write({
                    "club_latitude": coords[0],
                    "club_longitude": coords[1],
                    "club_geo_sig": sig,
                })
                _logger.debug("Geocoded %s -> %s", rec.display_name, coords)
        return True

    # ------------------------
    # Entry points (still usable manually)
    # ------------------------
    def action_locate_from_address(self):
        for rec in self:
            rec._geocode_if_needed(force=True)
        return True

    @api.onchange(*ADDRESS_FIELDS)
    def _onchange_autofill_coords(self):
        """
        Fill while editing, but only when address looks complete.
        (This writes only to in-memory fields; values persist on Save.)
        """
        for rec in self:
            if not ((rec.street or rec.street2) and (rec.city or rec.zip or rec.state_id) and rec.country_id):
                continue
            coords = rec._geocode_via_nominatim(rec._geo_address_line())
            if coords:
                rec.club_latitude, rec.club_longitude = coords

    # ------------------------
    # Auto-trigger on create/write
    # ------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Do network calls outside of super(); respect context flags.
        for rec in records:
            try:
                rec._geocode_if_needed(force=True)
            except Exception as e:
                _logger.info("Geocode on create failed for %s: %s", rec.display_name, e)
        return records

    def write(self, vals):
        address_changed = any(k in vals for k in ADDRESS_FIELDS)
        res = super().write(vals)
        if address_changed:
            for rec in self:
                try:
                    rec._geocode_if_needed(force=True)
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # ------------------------
    # Scheduled backfill (cron)
    # ------------------------
    def _cron_geocode_missing_contacts(self):
        """
        Backfill a small batch of partners missing coords, politely.
        System Parameter: geocode.nominatim.cron_limit (default 25)
        """
        ICP = self.env["ir.config_parameter"].sudo()
        try:
            limit = int(ICP.get_param("geocode.nominatim.cron_limit") or 25)
        except Exception:
            limit = 25

        domain = [
            "|", ("club_latitude", "=", False), ("club_longitude", "=", False),
            "|", ("street", "!=", False), ("street2", "!=", False),
            "|", ("city", "!=", False), ("zip", "!=", False),
            ("country_id", "!=", False),
        ]
        batch = self.search(domain, limit=limit, order="id asc")
        for rec in batch:
            try:
                rec._geocode_if_needed(force=True)
            except Exception as e:
                _logger.info("Cron geocode failed for %s: %s", rec.display_name, e)
        _logger.info("Cron geocode processed %s partners", len(batch))
        return True
