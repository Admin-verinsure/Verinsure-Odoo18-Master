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
    # Robust Nominatim geocoder (street-first, multi-pass with scoring)
    # ---------------------------------------------------------------------
    def _geocode_via_nominatim(self, addr, cc_lower=None):
        if not addr:
            return None

        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent}

        def _street_line():
            return ", ".join([p for p in [self.street or "", self.street2 or ""] if p]).strip(", ")

        def _params_structured(drop_state=False, drop_zip=False):
            p = {"format": "jsonv2", "limit": 5, "addressdetails": 1}
            sl = _street_line()
            if sl:
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

        def _params_q(full=True):
            q_text = addr if full else ", ".join([x for x in [
                _street_line(),
                self.city or "",
                (self.state_id and self.state_id.name) or "",
                (self.country_id and self.country_id.name) or "",
            ] if x])
            p = {"format": "jsonv2", "limit": 5, "addressdetails": 1, "q": q_text}
            if cc_lower:
                p["countrycodes"] = cc_lower
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

        for params in (
            _params_structured(False, False),
            _params_structured(True,  False),
            _params_structured(False, True),
            _params_q(True),
            _params_q(False),
        ):
            coords = _pick_best(_hit(params))
            if coords:
                return coords
        return None

    # ---------------------------------------------------------------------
    # WRITE helper: update both built-ins and club_* when available
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # Manual button (kept)
    # ---------------------------------------------------------------------
    def action_locate_from_address(self):
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
    # Auto on create/write (restore previous on failure → no 0.0)
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
    # *** Pre-render hook so first open shows coords immediately ***
    # ---------------------------------------------------------------------
    def _auto_geocode_on_form_open(self):
        """Run once when opening a form; write coords before the record is read."""
        self.ensure_one()
        if (self.env.context.get("install_mode")
                or self.env.context.get("disable_geocode")
                or self.env.context.get("no_geocode")):
            return False
        if getattr(self, "partner_latitude", False) and getattr(self, "partner_longitude", False):
            return False
        if not (self.country_id or self.state_id or self.city or self.street or self.street2 or self.zip):
            return False
        addr = self._geo_address_line()
        if not addr:
            return False
        coords = None
        try:
            coords = self._geocode_via_nominatim(addr)
        except Exception as e:
            _logger.info("Geocode on pre-open failed for %s: %s", self.display_name, e)
        if not coords and hasattr(self, "geo_find"):
            try:
                coords = self.geo_find(addr)
            except Exception:
                coords = None
        if coords:
            self.with_context(no_geocode=True).sudo()._write_coords_all(coords)
            return True
        return False

    @api.model
    def fields_view_get(self, view_id=None, view_type="form", toolbar=False, submenu=False):
        """
        Geocode & write coords for the active record BEFORE the form reads it.
        Fixes the 'first open shows 0.00' issue.
        """
        res = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        try:
            if view_type == "form":
                active_id = self.env.context.get("active_id")
                if active_id:
                    rec = self.browse(active_id)
                    if rec.exists():
                        rec._auto_geocode_on_form_open()
        except Exception as e:
            _logger.info("Auto geocode on form open skipped: %s", e)
        return res

    # ---------------------------------------------------------------------
    # Onchange (form preview) — preserve previous values on failure
    # ---------------------------------------------------------------------
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            old_plat = getattr(rec, "partner_latitude", False)
            old_plng = getattr(rec, "partner_longitude", False)
            old_clat = getattr(rec, "club_latitude", False) if "club_latitude" in rec._fields else False
            old_clng = getattr(rec, "club_longitude", False) if "club_longitude" in rec._fields else False

            addr = rec._geo_address_line()
            if not addr:
                if "partner_latitude" in rec._fields:  rec.partner_latitude  = old_plat
                if "partner_longitude" in rec._fields: rec.partner_longitude = old_plng
                if "club_latitude" in rec._fields:     rec.club_latitude     = old_clat
                if "club_longitude" in rec._fields:    rec.club_longitude    = old_clng
                continue

            coords = rec._geocode_via_nominatim(addr)
            if coords:
                if "partner_latitude" in rec._fields:  rec.partner_latitude  = coords[0]
                if "partner_longitude" in rec._fields: rec.partner_longitude = coords[1]
                if "club_latitude" in rec._fields:     rec.club_latitude     = coords[0]
                if "club_longitude" in rec._fields:    rec.club_longitude    = coords[1]
            else:
                if "partner_latitude" in rec._fields:  rec.partner_latitude  = old_plat
                if "partner_longitude" in rec._fields: rec.partner_longitude = old_plng
                if "club_latitude" in rec._fields:     rec.club_latitude     = old_clat
                if "club_longitude" in rec._fields:    rec.club_longitude    = old_clng
