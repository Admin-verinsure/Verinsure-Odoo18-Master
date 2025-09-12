# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")


class ResPartner(models.Model):
    _inherit = "res.partner"

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
    # Nominatim base (policy-friendly UA/email)
    # ---------------------------------------------------------------------
    def _nominatim_base(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (ICP.get_param("base.geolocalize.nominatim.server") or
                    "https://nominatim.openstreetmap.org").rstrip("/")
        user_agent = ICP.get_param("base.geolocalize.user_agent") or "mytest-geocode/1.0 (test)"
        contact_email = (ICP.get_param("base.geolocalize.contact_email") or "").strip()
        if contact_email and "@" not in contact_email:
            contact_email = ""
        return base_url, user_agent, contact_email

    # ---------------------------------------------------------------------
    # Two-phase geocoder: BASE (no street) → refine with street (keep BASE if fail)
    # ---------------------------------------------------------------------
    def _geocode_via_nominatim(self, addr, cc_lower=None):
        if not addr:
            return None

        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent}

        def _street_line():
            return ", ".join([p for p in [self.street or "", self.street2 or ""] if p]).strip(", ")

        def _params_structured(include_street=True, drop_state=False, drop_zip=False):
            p = {"format": "jsonv2", "limit": 5, "addressdetails": 1}
            sl = _street_line()
            if include_street and sl:
                p["street"] = sl
            if self.city:
                p["city"] = self.city
            if not drop_state and self.state_id and self.state_id.name:
                p["state"] = self.state_id.name
            if not drop_zip and self.zip:
                p["postalcode"] = self.zip
            if self.country_id and (self.country_id.name or self.country_id.code):
                p["country"] = self.country_id.name or ""
                p["countrycodes"] = (self.country_id.code or "").lower()
            if contact_email:
                p["email"] = contact_email
            return p

        def _params_q(include_street=True, full=True):
            parts = []
            if include_street:
                sl = _street_line()
                if sl:
                    parts.append(sl)
            if full:
                parts += [
                    self.city or "",
                    (self.state_id and self.state_id.name) or "",
                    self.zip or "",
                    (self.country_id and self.country_id.name) or "",
                ]
            else:
                parts += [
                    self.city or "",
                    (self.state_id and self.state_id.name) or "",
                    (self.country_id and self.country_id.name) or "",
                ]
            q_text = ", ".join([x for x in parts if x]) or addr
            p = {"q": q_text, "format": "jsonv2", "limit": 5, "addressdetails": 1}
            cc = (cc_lower or (self.country_id and (self.country_id.code or "")).lower() or "")
            if cc:
                p["countrycodes"] = cc
            if contact_email:
                p["email"] = contact_email
            return p

        def _score(c):
            score = 0.0
            ad = c.get("address") or {}
            t = (c.get("type") or "").lower()
            cls = (c.get("class") or "").lower()
            if t in {"house", "building", "residential"}:
                score += 20
            if cls == "building":
                score += 10
            if cls == "highway":
                score += 5
            st_given = (self.street or "").lower()
            st2_given = (self.street2 or "").lower()
            road = (ad.get("road") or ad.get("pedestrian") or ad.get("residential") or ad.get("footway") or "").lower()
            hnum = (ad.get("house_number") or "").lower()
            if st_given and road and st_given.split()[0] in road:
                score += 25
            if st2_given and road and st2_given.split()[0] in road:
                score += 10
            first_tok = st_given.split(",")[0].split(" ")[0] if st_given else ""
            if first_tok.isdigit() and hnum == first_tok:
                score += 15
            city_given = (self.city or "").lower()
            city_hit = (ad.get("city") or ad.get("town") or ad.get("village") or ad.get("suburb") or ad.get("county") or "").lower()
            if city_given and city_hit and city_given in city_hit:
                score += 15
            if self.zip and (ad.get("postcode") or "") == self.zip:
                score += 10
            if self.country_id and self.country_id.code and ((ad.get("country_code") or "").lower() == self.country_id.code.lower()):
                score += 5
            try:
                score += float(c.get("importance") or 0.0)
            except Exception:
                pass
            return score

        def _pick_best(results):
            if not results:
                return None
            best = max(results, key=_score)
            try:
                return float(best["lat"]), float(best.get("lon", best.get("lng")))
            except Exception:
                return None

        def _hit(params):
            try:
                r = requests.get(f"{base_url}/search", params=params, headers=headers, timeout=12)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                _logger.info("Nominatim error (%s): %s", params, e)
                return []

        # Phase A: base (no street)
        base_passes = (
            _params_structured(include_street=False, drop_state=False, drop_zip=False),
            _params_structured(include_street=False, drop_state=True,  drop_zip=False),
            _params_structured(include_street=False, drop_state=False, drop_zip=True),
            _params_q(include_street=False, full=True),
            _params_q(include_street=False, full=False),
        )
        base_coords = None
        for p in base_passes:
            base_coords = _pick_best(_hit(p))
            if base_coords:
                break

        # Phase B: refine with street (keep base if street fails)
        street_passes = (
            _params_structured(include_street=True, drop_state=False, drop_zip=False),
            _params_structured(include_street=True, drop_state=True,  drop_zip=False),
            _params_structured(include_street=True, drop_state=False, drop_zip=True),
            _params_q(include_street=True, full=True),
        )
        for p in street_passes:
            refined = _pick_best(_hit(p))
            if refined:
                return refined

        return base_coords

    def _write_coords_all(self, coords):
        if not coords:
            return
        F = self._fields
        vals = {}
        if "partner_latitude" in F:  vals["partner_latitude"]  = coords[0]
        if "partner_longitude" in F: vals["partner_longitude"] = coords[1]
        if "club_latitude" in F:     vals["club_latitude"]     = coords[0]
        if "club_longitude" in F:    vals["club_longitude"]    = coords[1]
        if vals:
            self.with_context(no_geocode=True).write(vals)

    # Manual button (unchanged)
    def action_locate_from_address(self):
        for rec in self:
            addr = rec._geo_address_line()
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

    # Geocode on create / write (keeps values in sync while editing)
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if self.env.context.get("install_mode") or self.env.context.get("disable_geocode"):
            return recs
        for rec in recs:
            try:
                addr = rec._geo_address_line()
                if addr:
                    coords = rec._geocode_via_nominatim(addr)
                    if coords:
                        rec._write_coords_all(coords)
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
                    if addr:
                        coords = rec._geocode_via_nominatim(addr)
                        if coords:
                            rec._write_coords_all(coords)
                except Exception as e:
                    _logger.info("Geocode on write failed for %s: %s", rec.display_name, e)
        return res

    # ---------------------------------------------------------------------
    # *** KEY PART ***: do it before the form returns data (no JS, no hidden field)
    # Only for single-record reads → avoids mass geocoding on list/kanban
    # ---------------------------------------------------------------------
    def read(self, fields=None, load="_classic_read"):
        if self.env.context.get("no_auto_geocode_read"):
            return super().read(fields=fields, load=load)

        try:
            if len(self) == 1:
                rec = self
                # Consider 0.0 as missing too
                lat = getattr(rec, "partner_latitude", 0.0) or 0.0
                lng = getattr(rec, "partner_longitude", 0.0) or 0.0
                missing = (abs(lat) < 1e-10) or (abs(lng) < 1e-10)
                has_addr = bool(rec.country_id or rec.state_id or rec.city or rec.street or rec.street2 or rec.zip)
                if missing and has_addr:
                    addr = rec._geo_address_line()
                    if addr:
                        coords = rec._geocode_via_nominatim(addr)
                        if not coords and hasattr(rec, "geo_find"):
                            try:
                                coords = rec.geo_find(addr)
                            except Exception:
                                coords = None
                        if coords:
                            rec.with_context(no_geocode=True, no_auto_geocode_read=True)._write_coords_all(coords)
        except Exception as e:
            _logger.info("Auto geocode inside read skipped: %s", e)

        # Ensure we don't recurse
        return super(ResPartner, self.with_context(no_auto_geocode_read=True)).read(fields=fields, load=load)
