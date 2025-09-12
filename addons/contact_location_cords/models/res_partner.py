# add near the top with your other imports
import re

# helpers (put inside the class)
def _ICP(self):
    return self.env["ir.config_parameter"].sudo()

def _cfg_bool(self, key, default=False):
    v = (self._ICP().get_param(key) or "").strip()
    if not v:
        return bool(default)
    return v not in ("0", "false", "False", "no", "No")

def _cfg_str(self, key, default=""):
    v = (self._ICP().get_param(key) or "").strip()
    return v if v else default

def _nom_mode(self):
    return (self._cfg_str("geocode.nominatim.mode", "balanced")).lower()

def _country_code_lower(self):
    return ((self.country_id and self.country_id.code) or "").lower()

def _lang_pref(self):
    lang_cfg = (self._ICP().get_param("base.geolocalize.language") or "").strip()
    return (lang_cfg or (self.env.user.lang or "en_US").split("_")[0])[:10]

def _nominatim_base(self):
    ICP = self._ICP()
    base_url = (ICP.get_param("base.geolocalize.nominatim.server") or
                "https://nominatim.openstreetmap.org").rstrip("/")
    user_agent = ICP.get_param("base.geolocalize.user_agent") or "odoo-geocode/1.0 (you@example.com)"
    contact_email = ICP.get_param("base.geolocalize.contact_email") or "you@example.com"
    return base_url, user_agent, contact_email

def _nominatim_call(self, path, params):
    base_url, user_agent, contact_email = self._nominatim_base()
    p = dict(params or {})
    p.setdefault("format", "jsonv2")
    p.setdefault("limit", 1)
    p.setdefault("addressdetails", 1)
    p.setdefault("email", contact_email)
    headers = {"User-Agent": user_agent, "Accept-Language": self._lang_pref()}
    r = requests.get(f"{base_url}{path}", params=p, headers=headers, timeout=12)
    r.raise_for_status()
    return r.json()

def _coords_from_result(self, r):
    try:
        return float(r["lat"]), float(r.get("lon", r.get("lng")))
    except Exception:
        return None

def _is_precise_enough(self, r):
    # allow city/ZIP fallback when strict_precision=0
    strict = self._cfg_bool("geocode.nominatim.strict_precision", True)
    addresstype = (r.get("addresstype") or "").lower()
    rtype = (r.get("type") or "").lower()
    address = r.get("address") or {}
    if address.get("house_number") or addresstype in {"house","building","address"} or rtype in {"house","building"}:
        return True
    if addresstype in {"road","street"} or rtype in {"road","residential","tertiary","secondary","primary","trunk"}:
        return True
    try:
        pr = int(r.get("place_rank") or 99)
        if pr <= 18:
            return True
    except Exception:
        pass
    return not strict   # if not strict, allow locality/ZIP

# optional, only if you used a "clean" function earlier
def _clean_street_line(self):
    # honor a switch to mimic older behavior
    if not self._cfg_bool("geocode.nominatim.street_clean", False):
        parts = [p.strip() for p in [self.street or "", self.street2 or ""] if p]
        return ", ".join(parts)
    # light cleaning
    line = ", ".join([p.strip() for p in [self.street or "", self.street2 or ""] if p])
    line = re.sub(r"\s+", " ", line).strip(" ,")
    return line

def _full_address_text(self):
    parts = [
        self._clean_street_line() or "",
        self.city or "",
        (self.state_id and self.state_id.name) or "",
        self.zip or "",
        (self.country_id and self.country_id.name) or "",
    ]
    return ", ".join([p for p in parts if p]).strip(", ")

def _viewbox_for_bias(self):
    if not self._cfg_bool("geocode.nominatim.bounded", True):
        return None
    cc = self._country_code_lower()
    # try postal code
    if self.zip:
        try:
            data = self._nominatim_call("/search", {"postalcode": self.zip, "countrycodes": cc or None})
            if isinstance(data, list) and data:
                s, n, w, e = map(float, data[0]["boundingbox"])  # [south,north,west,east]
                return [w, n, e, s]  # left, top, right, bottom
        except Exception:
            pass
    # try city
    if self.city:
        try:
            data = self._nominatim_call("/search", {
                "city": self.city,
                "state": (self.state_id and self.state_id.name) or None,
                "countrycodes": cc or None,
            })
            if isinstance(data, list) and data:
                s, n, w, e = map(float, data[0]["boundingbox"])
                return [w, n, e, s]
        except Exception:
            pass
    return None

# ------------------------
# MAIN: choose strategy by mode
# ------------------------
def _geocode_via_nominatim(self, _addr_ignored=None):
    """
    legacy:   q= free-text -> structured -> bounded
    balanced: structured -> bounded -> q=
    strict:   structured -> bounded -> q= (but require precise)
    """
    full_text = self._full_address_text()
    if not full_text:
        return None
    cc = self._country_code_lower()
    mode = self._nom_mode()
    prefer_q = self._cfg_bool("geocode.nominatim.prefer_q", mode == "legacy")

    # helpers
    def do_q(qtxt):
        params = {"q": qtxt, "countrycodes": cc or None}
        data = self._nominatim_call("/search", params)
        if isinstance(data, list) and data:
            r = data[0]
            return r, self._coords_from_result(r)
        return None, None

    def do_structured():
        params = {
            "street": self._clean_street_line() or None,
            "city": self.city or None,
            "state": (self.state_id and self.state_id.name) or None,
            "postalcode": self.zip or None,
            "country": (self.country_id and self.country_id.name) or None,
            "countrycodes": cc or None,
        }
        data = self._nominatim_call("/search", params)
        if isinstance(data, list) and data:
            r = data[0]
            return r, self._coords_from_result(r)
        return None, None

    def do_bounded(qtxt):
        vb = self._viewbox_for_bias()
        if not vb:
            return None, None
        left, top, right, bottom = vb
        params = {
            "q": qtxt,
            "countrycodes": cc or None,
            "viewbox": f"{left},{top},{right},{bottom}",
            "bounded": 1,
        }
        data = self._nominatim_call("/search", params)
        if isinstance(data, list) and data:
            r = data[0]
            return r, self._coords_from_result(r)
        return None, None

    # order of attempts
    attempts = []
    if prefer_q:
        attempts = [("q", lambda: do_q(full_text)),
                    ("structured", do_structured),
                    ("bounded", lambda: do_bounded(self._clean_street_line() or full_text))]
    else:
        attempts = [("structured", do_structured),
                    ("bounded", lambda: do_bounded(self._clean_street_line() or full_text)),
                    ("q", lambda: do_q(full_text))]

    for name, fn in attempts:
        r, coords = fn()
        if not coords:
            continue
        # precision check: strict only rejects coarse
        if mode == "strict" and not self._is_precise_enough(r):
            continue
        # legacy always accepts; balanced applies precision but allows fallback
        if mode == "legacy" or self._is_precise_enough(r):
            return coords

    return None
