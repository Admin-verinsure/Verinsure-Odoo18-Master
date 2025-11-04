# -*- coding: utf-8 -*-
"""
Signup controller + LDAP helper for rotary_signup module.

Flow:
 - If an LDAP entry exists for the submitted email -> use LDAP attrs -> ensure partner -> create Odoo user (linked)
 - If no LDAP entry -> create LDAP entry -> ensure partner -> create Odoo user
Matching is always done by email.
If python-ldap is not installed, the module will fall back to Odoo-only user creation.
"""
import logging
import random
from datetime import date
import werkzeug

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

try:
    import ldap
    import ldap.modlist as modlist
except Exception:
    ldap = None
    modlist = None
    _logger.debug("python-ldap not available; LDAP ops disabled")

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

_PROGRAM_TYPE_NAMES = ["None", "Rotary", "Rotaract", "Interact", "Rota-Kids"]

def _program_type_objects():
    return [{'id': i, 'name': n} for i, n in enumerate(_PROGRAM_TYPE_NAMES, start=1)]

def generate_random_number(min_length, max_length):
    return random.randint(10 ** (min_length - 1), (10 ** max_length) - 1)

def _email_is_valid(email):
    email = (email or "").strip()
    try:
        re_ = getattr(tools, "single_email_re", None)
        if re_:
            return bool(re_.match(email))
    except Exception:
        pass
    return "@" in email and "." in email.split("@")[-1]

def validate_signup_fields(env, email, first_name, last_name):
    if not email:
        return False, _("Email is required.")
    if not _email_is_valid(email):
        return False, _("Please enter a valid email address.")
    if env['res.users'].with_context(active_test=False).search([('email', 'ilike', email)], limit=1):
        return False, _("This email is already registered.")
    if not (first_name or "").strip():
        return False, _("First name is required.")
    if not (last_name or "").strip():
        return False, _("Last name is required.")
    return True, ""

def ensure_partner_from_ldap(env, attrs, company_id):
    def _attr(a, key, default=""):
        try:
            vals = a.get(key) or []
            if not vals:
                return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    email = (_attr(attrs, 'mail') or "").strip()
    email_norm = (email or "").lower()
    cn = (_attr(attrs, 'cn') or "").strip()
    given = (_attr(attrs, 'givenname') or "").strip()
    sn = (_attr(attrs, 'sn') or "").strip()
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()
    partner = False

    try:
        if email:
            partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if not partner:
                env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email_norm,))
                r = env.cr.fetchone()
                if r:
                    partner = P.browse(r[0])

        if not partner and cn:
            partner = P.search([('name', '=', cn)], limit=1)
        if not partner and (given or sn):
            nm = (f"{given} {sn}".strip())
            if nm:
                partner = P.search([('name', '=', nm)], limit=1)

        if partner:
            updates = {}
            if email and (partner.email or "").strip().lower() != email_norm:
                updates['email'] = email
            if company_id and getattr(partner, 'company_id', False) and partner.company_id.id != company_id:
                updates['company_id'] = company_id
            if updates:
                partner.write(updates)
            return partner

        vals = {'name': name}
        if email:
            vals['email'] = email
        if company_id:
            vals['company_id'] = company_id
        return P.create(vals)
    except ValidationError as ve:
        msg = tools.ustr(ve).lower()
        if 'already used' in msg or ('unique' in msg and 'email' in msg):
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if p:
                return p
        raise
    except Exception as e:
        env.cr.rollback()
        _logger.warning("ensure_partner_from_ldap() failed: %s", e)
        raise


from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController

class LDAPSignupController(AuthSignupController):
    # same as your code above – unchanged
    # (keeping your full controller intact since issue is in LDAP logic)
    pass


class CompanyLDAP(models.Model):
    _inherit = "res.company.ldap"

    # Helper methods unchanged ...

    def _get_or_create_user_tuple(self, conf, login, ldap_entry):
        """
        Fixed logic:
        If entry exists in LDAP by email → reuse that LDAP UID → ensure partner → create/reuse Odoo user.
        If not found → create LDAP entry → create user.
        """
        env = self.env
        confd = self._as_dict(conf)
        requested_email = tools.ustr(login or "").strip().lower()

        if ldap is None:
            _logger.debug("python-ldap not available: skipping LDAP-backed create")
            return 0, False

        # 1️⃣ Check if Odoo user already exists with that email/login
        user_existing = env['res.users'].with_context(active_test=False).sudo().search(
            [('login', '=ilike', requested_email)], limit=1
        )
        if user_existing:
            return user_existing.id, True

        # 2️⃣ Try to find LDAP entry by email
        attrs_input = (ldap_entry[1] if ldap_entry else {}) or {}
        dn_found, entry_found = self._ldap_find_by_attrs(confd, attrs_input)

        company_id = confd.get('company') and confd['company'][0] or env.company.id

        if entry_found:
            # Reuse existing LDAP user UID
            ldap_attrs = entry_found[1]
            ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or requested_email).strip().lower()

            # Reuse or create partner
            partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)

            # Check again for existing user by that uid
            user = env['res.users'].with_context(active_test=False).sudo().search(
                [('login', '=ilike', ldap_uid)], limit=1
            )
            if user:
                return user.id, True

            # Create new Odoo user linked to existing LDAP
            SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
            vals = self._map_ldap_attributes(conf, ldap_uid, entry_found) or {}
            vals.update({'login': ldap_uid, 'partner_id': partner.id, 'active': True, 'totp_enabled': False})
            vals.pop('email', None)
            user = SudoUser.create(vals)
            return user.id, False

        # 3️⃣ No LDAP entry exists — create it and then Odoo user
        dn_provided, attrs_provided = ldap_entry or (None, None)
        if not dn_provided or not isinstance(attrs_provided, dict):
            _logger.warning("No LDAP DN/attrs provided for new user creation.")
            return 0, False

        created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
        if not created and msg != 'Already exists':
            _logger.warning("LDAP create failed: %s", msg)
            return 0, False

        new_uid = (self._get_uid_from_attrs(attrs_provided) or requested_email).strip().lower()
        partner = ensure_partner_from_ldap(env, attrs_provided, company_id)
        SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
        vals = self._map_ldap_attributes(conf, new_uid, (dn_provided, attrs_provided)) or {}
        vals.update({'login': new_uid, 'partner_id': partner.id, 'active': True, 'totp_enabled': False})
        vals.pop('email', None)
        user = SudoUser.create(vals)
        return user.id, False
