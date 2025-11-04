# -*- coding: utf-8 -*-
"""
rotary_signup/signup.py

Aligned with the inherited (old) Odoo signup UI structure,
while preserving Rotary-specific member and non-member signup logic,
LDAP handling, and all functional elements from the previous working 427-line version.
"""

import logging
import random
import werkzeug
from datetime import date

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo.exceptions import ValidationError
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController

_logger = logging.getLogger(__name__)

# Accepted request params for signup
SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

# -----------------------------
# Helper functions
# -----------------------------

def generate_random_number(min_length, max_length):
    """Return a random integer with digits between min_length and max_length (inclusive length)."""
    return random.randint(10 ** (min_length - 1), (10 ** max_length) - 1)


def _email_is_valid(email):
    """Simple validation for email format."""
    email = (email or "").strip()
    try:
        re_ = getattr(tools, "single_email_re", None)
        if re_:
            return bool(re_.match(email))
    except Exception:
        pass
    return "@" in email and "." in email.split("@")[-1]


def validate_signup_fields(env, email, first_name, last_name):
    """Basic validation for signup inputs."""
    if not email:
        return False, _("Email is required.")
    if not _email_is_valid(email):
        return False, _("Please enter a valid email address.")
    if env['res.users'].with_context(active_test=False).search([('email', 'ilike', email)], limit=1):
        return False, _("This email is already registered as a user.")
    if not (first_name or "").strip():
        return False, _("First name is required.")
    if not (last_name or "").strip():
        return False, _("Last name is required.")
    return True, ""


def ensure_partner_from_ldap(env, attrs, company_id):
    """Find or create a partner record based on LDAP attributes."""
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
                env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s LIMIT 1", (email_norm,))
                r = env.cr.fetchone()
                if r:
                    partner = P.browse(r[0])
            except Exception:
                pass

    if not partner:
        vals = {'name': name, 'email': email, 'company_id': company_id}
        try:
            partner = P.create(vals)
        except ValidationError as ve:
            msg = tools.ustr(ve).lower()
            if 'unique' in msg and 'email' in msg:
                existing = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
                if existing:
                    partner = existing
            else:
                raise
    return partner

# -----------------------------
# Signup Controller
# -----------------------------

class RotarySignupController(AuthSignupController):
    """
    Rotary-specific signup controller (inherits standard Odoo signup templates)
    for both Members and Non-Members.
    """

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        """Landing: choose Member or Non-Member."""
        qcontext = self.get_auth_signup_qcontext()
        qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')

        # Inherit old login layout / signup flow
        return request.render('auth_signup.signup_is_member', qcontext)

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def signup_non_member(self, **kwargs):
        """Non-member signup (inherits standard Odoo signup UI)."""
        qcontext = self.get_auth_signup_qcontext()
        qcontext.setdefault('program_types', request.env['program.type'].sudo().search([], order='name'))

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, kwargs.get('email'), kwargs.get('first_name'), kwargs.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('auth_signup.signup_non_member', qcontext)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('auth_signup.signup_non_member', qcontext)

                sn, fn = kwargs['last_name'], kwargs['first_name']
                rotary_id = str(generate_random_number(5, 8))
                login = f"{sn}{rotary_id}"
                cn = f"{fn} {sn}"
                dn = f"uid={login}, {ldap_rec.ldap_base}"

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "employeeNumber": [rotary_id.encode()],
                    "mail": [kwargs['email'].encode()],
                    "userPassword": [kwargs['password'].encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                partner = ensure_partner_from_ldap(env, attrs, ldap_rec.company.id)
                user = env['res.users'].sudo().create({
                    'login': login.lower(),
                    'partner_id': partner.id,
                    'active': True,
                    'name': cn,
                })

                # Assign Guest role
                role = env['res.users.role'].search([('name', '=', 'Guests')], limit=1)
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
                        _logger.warning("Could not set groups for user %s", user.id)

                program_type_id = kwargs.get('program_type_id')
                if program_type_id:
                    user.partner_id.sudo().write({'program_type_id': int(program_type_id)})

                return request.render('auth_signup.web_thanks', {
                    'message': _('You have created user: %s') % user.login
                })

            except Exception as e:
                _logger.exception("Non-member signup error: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('auth_signup.signup_non_member', qcontext)

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def signup_member(self, **kwargs):
        """Member signup (inherits old auth_signup templates)."""
        qcontext = self.get_auth_signup_qcontext()
        qcontext['clubs'] = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, kwargs.get('email'), kwargs.get('first_name'), kwargs.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('auth_signup.signup', qcontext)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('auth_signup.signup', qcontext)

                sn, fn = kwargs['last_name'], kwargs['first_name']
                rotary_id = kwargs.get('rotary_id', '')
                login = f"{sn}{rotary_id}"
                cn = f"{fn} {sn}"
                dn = f"uid={login}, {ldap_rec.ldap_base}"

                rotary_club_id = int(kwargs.get('rotary_club_id', 0)) if kwargs.get('rotary_club_id') else 0

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "ou": [str(rotary_club_id).encode()],
                    "employeeNumber": [rotary_id.encode()],
                    "mail": [kwargs['email'].encode()],
                    "userPassword": [kwargs['password'].encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                partner = ensure_partner_from_ldap(env, attrs, ldap_rec.company.id)
                user = env['res.users'].sudo().create({
                    'login': login.lower(),
                    'partner_id': partner.id,
                    'active': True,
                    'name': cn,
                })

                partner.write({
                    'rotary_club_id': rotary_club_id,
                    'rotary_membership_id': rotary_id,
                })

                # Assign Member role
                role = env['res.users.role'].search([('name', '=', 'Members')], limit=1)
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
                        _logger.warning("Could not set groups for user %s", user.id)

                program_type_id = kwargs.get('program_type_id')
                if program_type_id:
                    user.partner_id.sudo().write({'program_type_id': int(program_type_id)})

                return request.render('auth_signup.web_thanks', {
                    'message': _('You have created user: %s') % user.login
                })

            except Exception as e:
                _logger.exception("Member signup error: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('auth_signup.signup', qcontext)

    def get_auth_signup_qcontext(self):
        """Collect request params and populate from signup token if present."""
        qcontext = {k: v for (k, v) in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
        qcontext.update(self.get_auth_signup_config())
        if not qcontext.get('token') and request.session.get('auth_signup_token'):
            qcontext['token'] = request.session.get('auth_signup_token')
        if qcontext.get('token'):
            try:
                info = request.env['res.partner'].sudo().signup_retrieve_info(qcontext['token'])
                for k, v in info.items():
                    qcontext.setdefault(k, v)
            except Exception:
                qcontext['error'] = _("Invalid signup token")
                qcontext['invalid_token'] = True
        return qcontext
