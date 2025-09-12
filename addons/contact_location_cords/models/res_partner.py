# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

ADDR_FIELDS = ("street", "street2", "city", "state_id", "zip", "country_id")


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Hidden, non-stored trigger so compute runs on form open
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
        """
        Robust Nominatim search:
          1) structured with all fields, limit=5
          2) structured without state (common mismatch)
          3) structured without postalcode
          4) full-text q= with everything
          5) full-text q= lighter (no zip)
          -> pick best candidate with scoring (street/house/city/zip/class).
        Returns (lat, lon) or None.
        """
        if not addr:
            return None

        base_url, user_agent, contact_email = self._nominatim_base()
        headers = {"User-Agent": user_agent}

        def _street_line():
            return ", ".join([p for p in [self.street or "", self.street2 or ""] if p]).strip(", ")

        def _params_structured(drop_state=False, drop_zip=False):
            p = {
                "format": "jsonv2",
                "limit": 5,
                "addressdetails": 1,
            }
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
            if full:
                q_text = addr
            else:
                q_text = ", ".join([x for x in [
                    _street_line(),
                    self.city or "",
                    (self.state_id and self.state_id.name) or "",
                    (self.country_id and self.country_id.name) or "",
                ] if x])
            p = {
                "format": "jsonv2",
                "limit": 5,
                "addressdetails": 1,
                "q": q_text,
            }
            if cc_lower:
                p["countrycodes"] = cc_lower
            if contact_email:
                p["email"] = contact_email
            return p

        def _score(c):
            """Higher is better. Reward street/house/city/zip matches."""
            score = 0.0
            ad = c.get("address") or {}
            # class/type preference: buildings/addresses > streets > cities
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

            # street token match
            if st_given and road and st_given.split()[0] in road:
                score += 25
            if st2_given and road and st2_given.split()[0] in road:
                score += 10
            # leading house number match
            first_tok = st_given.split(",")[0].split(" ")[0] if st_given else ""
            if first_tok.isdigit() and hnum == first_tok:
                score += 15

            # city/town/village/suburb
            city_given = (self.city or "").lower()
            city_hit = (ad.get("city") or ad.get("town") or ad.get("village") or ad.get("suburb") or ad.get("county") or "").lower()
            if city_given and city_hit and city_given in city_hit:
                score += 15

            # postcode
            if self.zip and (ad.get("postcode") or "") == self.zip:
                score += 10

            # country bias
            if self.country_id and self.country_id.code and ((ad.get("country_code") or "").lower() == self.country_id.code.lower()):
                score += 5

            # Nominatim's own importance
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

        # Pass 1: structured strict
        data = _hit(_params_structured(drop_state=False, drop_zip=False))
        coords = _pick_best(data)
        if coords:
            return coords

        # Pass 2: drop state (frequent mismatch)
        data = _hit(_params_structured(drop_state=True, drop_zip=False))
        coords = _pick_best(data)
        if coords:
            return coords

        # Pass 3: drop zip (often missing)
        data = _hit(_params_structured(drop_state=False, drop_zip=True))
        coords = _pick_best(data)
        if coords:
            return coords

        # Pass 4: full-text all
        data = _hit(_params_q(full=True))
        coords = _pick_best(data)
        if coords:
            return coords

        # Pass 5: full-text lighter (no zip)
        data = _hit(_params_q(full=False))
        coords = _pick_best(data)
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

        # snapshot previous to avoid ending with 0.0 on failure
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
                        # restore previous values (so UI doesn't show 0.0)
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
    # Onchange (form preview) — preserve previous values on failure
    # ---------------------------------------------------------------------
    @api.onchange(*ADDR_FIELDS)
    def _onchange_autofill_coords(self):
        for rec in self:
            # snapshot current on-screen values
            old_plat = getattr(rec, "partner_latitude", False)
            old_plng = getattr(rec, "partner_longitude", False)
            old_clat = getattr(rec, "club_latitude", False) if "club_latitude" in rec._fields else False
            old_clng = getattr(rec, "club_longitude", False) if "club_longitude" in rec._fields else False

            addr = rec._geo_address_line()
            if not addr:
                # keep previous values; do not zero
                if "partner_latitude" in rec._fields:  rec.partner_latitude  = old_plat
                if "partner_longitude" in rec._fields: rec.partner_longitude = old_plng
                if "club_latitude" in rec._fields:     rec.club_latitude     = old_clat
                if "club_longitude" in rec._fields:    rec.club_longitude    = old_clng
                continue

            coords = rec._geocode_via_nominatim(addr)
            if coords:
                # update on-screen values (not persisted until Save)
                if "partner_latitude" in rec._fields:  rec.partner_latitude  = coords[0]
                if "partner_longitude" in rec._fields: rec.partner_longitude = coords[1]
                if "club_latitude" in rec._fields:     rec.club_latitude     = coords[0]
                if "club_longitude" in rec._fields:    rec.club_longitude    = coords[1]
            else:
                # explicitly restore previous so UI doesn't show 0.0
                if "partner_latitude" in rec._fields:  rec.partner_latitude  = old_plat
                if "partner_longitude" in rec._fields: rec.partner_longitude = old_plng
                if "club_latitude" in rec._fields:     rec.club_latitude     = old_clat
                if "club_longitude" in rec._fields:    rec.club_longitude    = old_clng
