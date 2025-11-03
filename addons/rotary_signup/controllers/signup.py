# -*- coding: utf-8 -*-
"""
ldap_signup/main.py

Signup-only module:
 - provides member / non-member signup controllers (web routes)
 - contains local helpers (validation, partner ensure, random id)
 - uses env['res.company.ldap'] for LDAP configuration and (if present) for LDAP create/lookups.

Note: This file intentionally DOES NOT re-implement CompanyLDAP model overrides
to avoid conflicting duplicate model definitions if you keep the reset-password addon
with its LDAP model. If you need a fully standalone file that also implements the
LDAP model override, ask and I'll produce a duplicated-version.
"""
import logging
import random

from datetime import date
from ldap.filter import filter_format

import werkzeug

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# request params we accept on signup pages (kept similar to original)
SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

# -----------------------------
# Small helpers (local to signup)
# -----------------------------

def generate_random_number(min_length, max_length):
    """Return a random integer with digits between min_length and max_length (inclusive length)."""
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
    """Basic validation used by signup forms."""
    if not email:
        return False, _("Email is required.")
    if not _email_is_valid(email):
        return False, _("Please enter a valid email address.")
    U = env['res.users'].with_context(active_test=False)
    if U.search([('email', 'ilike', email)], limit=1):
        return False, _("This email is already registered as a user.")
    if not (first_name or "").strip():
        return False, _("First name is required.")
    if not (last_name or "").strip():
        return False, _("Last name is required.")
    return True, ""

def ensure_partner_from_ldap(env, attrs, company_id):
    """
    Idempotent partner lookup/create by LDAP attrs.
    Reuses existing partner when email uniqueness conflicts occur.
    """
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
    email_norm = email.lower()
    cn = (_attr(attrs, 'cn') or "").strip()
    given = (_attr(attrs, 'givenname') or "").strip()
    sn = (_attr(attrs, 'sn') or "").strip()
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()

    partner = False
    if email:
        partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
        if not partner:
            try:
                env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email_norm,))
                r = env.cr.fetchone()
                if r:
                    partner = P.browse(r[0])
            except Exception:
                pass

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
        if company_id and partner.company_id.id != company_id:
            updates['company_id'] = company_id
        if updates:
            partner.write(updates)
        return partner

    vals = {'name': name}
    if email:
        vals['email'] = email
    if company_id:
        vals['company_id'] = company_id
    try:
        return P.create(vals)
    except ValidationError as ve:
        # Attempt to recover from unique constraint by locating the existing partner
        msg = tools.ustr(ve).lower()
        if 'already used' in msg or ('unique' in msg and 'email' in msg):
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if not p and email:
                try:
                    env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email_norm,))
                    r = env.cr.fetchone()
                    if r:
                        p = P.browse(r[0])
                except Exception:
                    pass
            if p:
                return p
        raise
    except Exception as e:
        msg = tools.ustr(e).lower()
        if 'unique' in msg and 'email' in msg:
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if p:
                return p
        raise

# -----------------------------
# Signup Controller
# -----------------------------

from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController

class LDAPSignupController(AuthSignupController):
    """
    Signup controller subclass for member/non-member signup.
    Relies on env['res.company.ldap'] to provide LDAP configuration and
    (preferably) supporting methods such as _get_or_create_user_tuple / _create_ldap_user.
    """

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        qcontext = self.get_auth_signup_qcontext()
        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])
        return request.render('ldap_signup.signup_is_member', qcontext)

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        try:
            qcontext.setdefault('program_types', request.env['program.type'].sudo().search([], order='name'))
        except Exception:
            qcontext.setdefault('program_types', request.env['ir.model'].sudo().browse([]))

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_signup.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                # Use LDAP config record for base dn / create operations
                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    resp = request.render('ldap_signup.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                # build identity
                sn = qcontext['last_name']; fn = qcontext['first_name']
                rotaryId = str(generate_random_number(5, 8))
                login = f"{sn}{rotaryId}"
                cn = f"{fn} {sn}"
                dn = f"uid={login}, {ldap_rec.ldap_base}"

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "employeeNumber": [rotaryId.encode()],
                    "mail": [qcontext['email'].encode()],
                    "userPassword": [qcontext['password'].encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                # Prefer using existing LDAP helper if available
                if hasattr(ldap_rec, '_get_or_create_user_tuple'):
                    user_id, existing = ldap_rec._get_or_create_user_tuple(ldap_rec, qcontext['email'], (dn, attrs))
                else:
                    # fallback: try to create minimal Odoo user via partner creation
                    partner = ensure_partner_from_ldap(env, attrs, ldap_rec.company.id if hasattr(ldap_rec, 'company') and ldap_rec.company else env.company.id)
                    SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
                    vals = {
                        'login': login.lower(),
                        'partner_id': partner.id,
                        'active': True,
                        'name': cn,
                    }
                    user = SudoUser.create(vals)
                    user_id, existing = user.id, False

                if existing:
                    return request.render('ldap_signup.web_error', {'message': _('Error: User already exists.')})

                if isinstance(user_id, int) and user_id:
                    # If LDAP helper didn't add LDAP entry, attempt to create it if method exists
                    if hasattr(ldap_rec, '_ldap_find_by_attrs') and hasattr(ldap_rec, '_create_ldap_user'):
                        dn_exist, entry_exist = ldap_rec._ldap_find_by_attrs(ldap_rec, attrs)
                        if not entry_exist:
                            created, message = ldap_rec._create_ldap_user(ldap_rec, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                # rollback created Odoo user if present
                                try:
                                    env['res.users'].sudo().browse(user_id).unlink()
                                except Exception:
                                    _logger.exception("Could not unlink created user after LDAP create failure")
                                return request.render('ldap_signup.web_error', {'message': (message or '') + '.'})

                    # Post-create updates: assign 'Guests' role, program_type etc.
                    user = env['res.users'].sudo().browse(user_id)
                    role = env['res.users.role'].search([('name', '=', 'Guests')], limit=1)
                    # set rotary membership id on partner
                    if rotaryId.isdigit():
                        try:
                            user.partner_id.write({'rotary_membership_id': str(rotaryId)})
                        except Exception:
                            _logger.warning("Could not write rotary_membership_id.")

                    # remove any existing role lines and add guest role line
                    env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                    if role:
                        env['res.users.role.line'].create({
                            'user_id': user.id,
                            'role_id': role.id,
                            'date_from': date.today(),
                            'date_to': date(2099, 12, 31),
                        })
                        try:
                            user.set_groups_from_roles()
                        except Exception:
                            _logger.warning("Could not call set_groups_from_roles on user %s", user.id)

                    program_type_id = qcontext.get('program_type_id')
                    if program_type_id:
                        try:
                            user.partner_id.sudo().write({'program_type_id': int(program_type_id)})
                        except Exception:
                            _logger.warning("SIGNUP: could not set program_type_id on partner %s", user.partner_id.id)

                    return request.render('ldap_signup.web_thanks', {'message': _('You have created user: %s') % user.login})
                else:
                    qcontext['error'] = _("Could not create a new account. %s" % str(user_id))
            except Exception as e:
                _logger.exception("Signup non-member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        resp = request.render('ldap_signup.signup_non_member', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        """
        Member signup (rotary members). Similar flow to non-member but uses rotary_id/club.
        """
        qcontext = self.get_auth_signup_qcontext()
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_signup.signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    resp = request.render('ldap_signup.signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                sn = qcontext['last_name']; fn = qcontext['first_name']
                rotaryId = qcontext.get('rotary_id') or ""
                login = f"{sn}{rotaryId}"
                cn = f"{fn} {sn}"
                dn = f"uid={login}, {ldap_rec.ldap_base}"

                try:
                    rotary_club_id = int(qcontext.get('rotary_club_id', 0))
                except Exception:
                    rotary_club_id = 0

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "ou": [str(rotary_club_id).encode()],
                    "employeeNumber": [rotaryId.encode()],
                    "mail": [qcontext['email'].encode()],
                    "userPassword": [qcontext['password'].encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                if hasattr(ldap_rec, '_get_or_create_user_tuple'):
                    user_id, existing = ldap_rec._get_or_create_user_tuple(ldap_rec, qcontext['email'], (dn, attrs))
                else:
                    # fallback similar to non-member
                    partner = ensure_partner_from_ldap(env, attrs, ldap_rec.company.id if hasattr(ldap_rec, 'company') and ldap_rec.company else env.company.id)
                    SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
                    vals = {'login': login.lower(), 'partner_id': partner.id, 'active': True, 'name': cn}
                    user = SudoUser.create(vals)
                    user_id, existing = user.id, False

                if existing:
                    return request.render('ldap_signup.web_error', {'message': _('Error: User already exists.')})

                if isinstance(user_id, int) and user_id:
                    user = env['res.users'].sudo().browse(user_id)
                    # write club & rotary id on partner
                    try:
                        if rotaryId.isdigit():
                            user.partner_id.write({'rotary_club_id': rotary_club_id, 'rotary_membership_id': str(rotaryId)})
                        else:
                            user.partner_id.write({'rotary_club_id': rotary_club_id})
                    except Exception:
                        _logger.warning("Could not write partner club/rotary fields for user %s", user_id)

                    role = env['res.users.role'].search([('name', '=', 'Members')], limit=1)
                    env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                    if role:
                        env['res.users.role.line'].create({
                            'user_id': user.id,
                            'role_id': role.id,
                            'date_from': date.today(),
                            'date_to': date(2099, 12, 31),
                        })
                        try:
                            user.set_groups_from_roles()
                        except Exception:
                            _logger.warning("Could not set groups from roles for user %s", user_id)

                    program_type_id = qcontext.get('program_type_id')
                    if program_type_id:
                        try:
                            user.partner_id.sudo().write({'program_type_id': int(program_type_id)})
                        except Exception:
                            _logger.warning("SIGNUP: could not set program_type_id on partner %s", user.partner_id.id)

                    return request.render('ldap_signup.web_thanks', {'message': _('You have created user: %s') % user.login})
                else:
                    qcontext['error'] = _("Could not create a new account. %s") % str(user_id)
            except Exception as e:
                _logger.exception("Signup member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        resp = request.render('ldap_signup.signup', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    def get_auth_signup_qcontext(self):
        """
        Collect whitelisted request params and populate from signup token if present
        """
        qcontext = {k: v for (k, v) in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
        qcontext.update(self.get_auth_signup_config())
        if not qcontext.get('token') and request.session.get('auth_signup_token'):
            qcontext['token'] = request.session.get('auth_signup_token')
        if qcontext.get('token'):
            try:
                for k, v in request.env['res.partner'].sudo().signup_retrieve_info(qcontext.get('token')).items():
                    qcontext.setdefault(k, v)
            except Exception:
                qcontext['error'] = _("Invalid signup token")
                qcontext['invalid_token'] = True
        return qcontext
