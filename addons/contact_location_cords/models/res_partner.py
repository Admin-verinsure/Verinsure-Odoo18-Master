# -*- coding: utf-8 -*-
import logging
import re
import requests
from odoo import models, api

_logger = logging.getLogger(__name__)

# Conservative cleanup: keep it multilingual-safe; don't over-strip.
NOISE_TOKENS = re.compile(
    r"\b(near|opp(?:osite)?|beside|behind|landmark|apt\.?|suite|ste\.?|unit|floor|fl\.?|tower|bldg\.?)\b",
    flags=re.I
)

class ResPartner(models.Model):
    _inherit = "res.partner"  # fields defined elsewhere

    # ------------------------
    # Config & helpers
    # ------------------------
    def _ICP(self):
        return self.env["ir.config_parameter"].sudo()

    def _lang_pref(self):
        lang_cfg = (self._ICP().get_param("base.geolocalize.language") or "").strip()
        if lang_cfg:
            return lang_cfg[:10]
        # fallback to current user's lang (en_US -> en)
        return (self.env.user.lang or "en_US").split("_")[0][:10]

    def _country_code_lower(self):
        return ((self.country_id and self.country_id.code) or "").lower()

    def _clean_street_line(self):
        self.ensure_one()
        parts = [p.strip() for p in [self.street or "", self.street2 or ""] if p]
        line = ", ".join(parts)
        line = NOISE_TOKENS.sub("", line)
        line = re.sub(r"[#;]", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" ,")
        return line

    def _full_address_text(self):
        self.ensure_one()
        parts = [
            self._clean_street_line() or "",
            self.city or "",
            (self.state_id and self.state_id.name) or "",
            self.zip or "",
            (self.country_id and self.country_id.name) or "",
        ]
        return ", ".join([p for p in parts if p]).strip(", ")

    # ------------------------
    # Nominatim core
    # ------------------------
    def _nominatim_base(self):
        ICP = self._ICP()
        base_url = (ICP.get_param("base.geolocalize.nominatim.server") or
                    "https://nominatim.openstreetmap.org").rstrip("/")
        user_agent = ICP.get_param("base.geolocalize.user_agent") or \
                     "your-app/1.0 (you@example.com)"
        contact_email = ICP.get_param("base.geolocalize.contact_email") or \
                        "you@example.com"
        return base_url, user_agent, contact_email

    def _nominatim_call(self, path, params):
        base_url, user_agent, contact_email = self._nominatim_base()
        params = dict(params or {})
        params.setdefault("format", "jsonv2")
        params.setdefault("limit", 1)
        params.setdefault("addressdetails", 1)
        params.setdefault("email", contact_email)
        headers = {
            "User-Agent": user_agent,
            "Accept-Language": self._lang_pref(),
        }
        r = requests.get(f"{base_url}{path}", params=params, headers=headers, timeout=12)
        r.raise_for_status()
        return r.json()

    def _coords_from_result(self, r):
        try:
            return float(r["lat"]), float(r.get("lon", r.get("lng")))
        except Exception:
            return None

    def _is_precise_enough(self, r):
        """
        Accept house/building or street-level; reject city/ZIP unless config allows.
        """
        strict = (self._ICP().get_param("geocode.nominatim.strict_precision") or "1") not in ("0", "false", "False")
        addresstype = (r.get("addresstype") or "").lower()
        rtype = (r.get("type") or "").lower()
        address = r.get("address") or {}
        has_hn = bool(address.get("house_number"))

        # Strong signals of rooftop/building/street
        street_ok = addresstype in {"road", "street"} or rtype in {"road", "residential", "tertiary", "secondary", "primary", "trunk"}
        building_ok = has_hn or addresstype in {"house", "building", "address"} or rtype in {"house", "building"}

        if building_ok or street_ok:
            return True

        # Place rank heuristic: <=18 is usually address/street; >20 is locality/town
        try:
            pr = int(r.get("place_rank") or 99)
            if pr <= 18:
                return True
        except Exception:
            pass

        # If not strict, allow locality fallback
        return not strict

    def _viewbox_for_bias(self):
        """
        Find a bounding box to bias searches: postal code first, else city.
        Returns [left, top, right, bottom] or None.
        """
        cc = self._country_code_lower()

        # Try postal code
        if self.zip:
            try:
                data = self._nominatim_call("/search", {"postalcode": self.zip, "countrycodes": cc or None})
                if isinstance(data, list) and data:
                    bb = data[0].get("boundingbox")  # [south, north, west, east]
                    if bb and len(bb) == 4:
                        s, n, w, e = map(float, bb)
                        return [w, n, e, s]
            except Exception:
                pass

        # Try city
        if self.city:
            try:
                data = self._nominatim_call("/search", {
                    "city": self.city,
                    "state": (self.state_id and self.state_id.name) or None,
                    "countrycodes": cc or None,
                })
                if isinstance(data, list) and data:
                    bb = data[0].get("boundingbox")
                    if bb and len(bb) == 4:
                        s, n, w, e = map(float, bb)
                        return [w, n, e, s]
            except Exception:
                pass
        return None

    def _geocode_via_nominatim(self):
        """
        Multi-stage:
          1) Structured search (street/city/state/postalcode/country)
          2) Bounded free-text within ZIP/city viewbox
          3) Unbounded free-text (last resort)
        Returns (lat, lon) or None.
        """
        street_line = self._clean_street_line()
        full_text = self._full_address_text()
        cc = self._country_code_lower()
        if not full_text:
            return None

        # 1) Structured
        try:
            sparams = {
                "street": street_line or None,
                "city": self.city or None,    # works for city/town/village
                "state": (self.state_id and self.state_id.name) or None,
                "postalcode": self.zip or None,
                "country": (self.country_id and self.country_id.name) or None,
                "countrycodes": cc or None,
            }
            data = self._nominatim_call("/search", sparams)
            if isinstance(data, list) and data:
                r = data[0]
                coords = self._coords_from_result(r)
                if coords and self._is_precise_enough(r):
                    return coords
        except Exception as e:
            _logger.info("Nominatim structured error: %s", e)

        # 2) Bounded free-text
        try:
            vb = self._viewbox_for_bias()
            if vb:
                left, top, right, bottom = vb
                bparams = {
                    "q": street_line or full_text,
                    "countrycodes": cc or None,
                    "viewbox": f"{left},{top},{right},{bottom}",
                    "bounded": 1,
                }
                data = self._nominatim_call("/search", bparams)
                if isinstance(data, list) and data:
                    r = data[0]
                    coords = self._coords_from_result(r)
                    if coords and self._is_precise_enough(r):
                        return coords
        except Exception as e:
            _logger.info("Nominatim bounded error: %s", e)

        # 3) Unbounded free-text
        try:
            data = self._nominatim_call("/search", {"q": full_text, "countrycodes": cc or None})
            if isinstance(data, list) and data:
                r = data[0]
                coords = self._coords_from_result(r)
                if coords and self._is_precise_enough(r):
                    return coords
                # If strict precision, refuse coarse matches:
                if coords:
                    _logger.info("Result too coarse for strict mode: %s", r.get("display_name"))
        except Exception as e:
            _logger.info("Nominatim free-text error: %s", e)

        return None

    # ------------------------
    # Entry points
    # ------------------------
    def action_locate_from_address(self):
        """Button: geocode and WRITE coords."""
        for rec in self:
            coords = rec._geocode_via_nominatim()
            if coords:
                rec.write({"club_latitude": coords[0], "club_longitude": coords[1]})
        return True

    @api.onchange("street", "street2", "city", "state_id", "zip", "country_id")
    def _onchange_autofill_coords(self):
        """
        Fill lat/lon while editing, but only when we have enough info.
        This avoids hitting Nominatim on every keystroke.
        """
        for rec in self:
            if not (rec.street or rec.street2):
                continue
            if not (rec.country_id and (rec.city or rec.zip or rec.state_id)):
                continue
            coords = rec._geocode_via_nominatim()
            if coords:
                rec.club_latitude = coords[0]
                rec.club_longitude = coords[1]
