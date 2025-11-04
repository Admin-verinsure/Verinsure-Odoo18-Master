# -*- coding: utf-8 -*-
import logging
import random
from datetime import date
import werkzeug

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

# --- static program types (old behavior) ---
_PROGRAM_TYPE_NAMES = ["None", "Rotary", "Rotaract", "Interact", "Rota-Kids"]

def _program_type_objects():
    """
    Return simple objects with .id and .name so QWeb expressions like
    <t t-foreach="program_types" t-as="ptype"><option t-att-value="ptype.id"><t t-esc="ptype.name"/></option>
    work as expected.
    """
    objs = []
    for i, name in enumerate(_PROGRAM_TYPE_NAMES, start=1):
        objs.append(type("PT", (), {"id": i, "name": name})())
    return objs

# -----------------------------
# Helpers
# -----------------------------
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
    email_norm = (email or "").lower()
    cn = (_attr(attrs, 'cn') or "").strip()
    given = (_attr(attrs, 'givenname') or "").strip()
    sn = (_attr(attrs, 'sn') or "").strip()
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()

    partner = False
    if email:
        partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
        if not partner:
            # fallback direct SQL search to avoid active_test issues
            try:
                env.cr.execute(
                    "SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1",
                    (email_norm,))
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
                    env.cr.execute(
                        "SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1",
                        (email_norm,))
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
    Uses rotary_signup templates and restores old program/club behavior.
    """

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        """First step: Ask user if they're a Rotary member."""
        qcontext = self.get_auth_signup_qcontext()
        # no heavy model lookups here; template is static choice page
        return request.render('rotary_signup.signup_is_member', qcontext)

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()

        # Do not expose program types for non-members (old behavior didn't show them)
        qcontext['program_types'] = []  # template will show default option only
        # also do not populate clubs for non-members
        qcontext['clubs'] = []

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('rotary_signup.signup_non_member', qcontext)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('rotary_signup.signup_non_member', qcontext)

                sn = qcontext.get('last_name', '')
                fn = qcontext.get('first_name', '')
                rotaryId = str(generate_random_number(5, 8))
                login = f"{sn}{rotaryId}"
                cn = f"{fn} {sn}"
                # build attrs for partner/ldap fallback
                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "employeeNumber": [rotaryId.encode()],
                    "mail": [qcontext.get('email', '').encode()],
                    "userPassword": [qcontext.get('password', '').encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                partner = ensure_partner_from_ldap(env, attrs, ldap_rec.company.id if getattr(ldap_rec, 'company', False) else env.company.id)
                user = env['res.users'].sudo().create({
                    'login': login.lower(),
                    'partner_id': partner.id,
                    'active': True,
                    'name': cn,
                })

                # set rotary id on partner
                if rotaryId.isdigit():
                    try:
                        user.partner_id.write({'rotary_membership_id': str(rotaryId)})
                    except Exception:
                        _logger.warning("Could not write rotary_membership_id for non-member user %s", user.id)

                # assign Guests role if present
                role = env['res.users.role'].search([('name', '=', 'Guests')], limit=1)
                env['res.users.role.line'].search([('user_id', '=', user.id)]).unlink()
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

                return request.render('rotary_signup.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                _logger.exception("Signup non-member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('rotary_signup.signup_non_member', qcontext)

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        """Signup for Rotary Members"""
        qcontext = self.get_auth_signup_qcontext()

        # Load rotary clubs from partners (old behaviour)
        try:
            clubs = request.env['res.partner'].sudo().search([('is_rotary_club', '=', True)])
        except Exception:
            clubs = request.env['res.partner'].sudo().search([])
        qcontext['clubs'] = clubs

        # Provide static program types as simple objects with id/name
        qcontext['program_types'] = _program_type_objects()

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('rotary_signup.signup', qcontext)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('rotary_signup.signup', qcontext)

                sn = qcontext.get('last_name', '')
                fn = qcontext.get('first_name', '')
                rotaryId = qcontext.get('rotary_id') or ""
                login = f"{sn}{rotaryId}"
                cn = f"{fn} {sn}"

                try:
                    rotary_club_id = int(qcontext.get('rotary_club_id', 0) or 0)
                except Exception:
                    rotary_club_id = 0

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "ou": [str(rotary_club_id).encode()],
                    "employeeNumber": [rotaryId.encode()],
                    "mail": [qcontext.get('email', '').encode()],
                    "userPassword": [qcontext.get('password', '').encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                partner = ensure_partner_from_ldap(env, attrs, ldap_rec.company.id if getattr(ldap_rec, 'company', False) else env.company.id)
                user = env['res.users'].sudo().create({
                    'login': login.lower(),
                    'partner_id': partner.id,
                    'active': True,
                    'name': cn,
                })

                # Set club and rotary id on partner
                try:
                    if rotaryId and rotaryId.isdigit():
                        partner_vals = {'rotary_club_id': rotary_club_id, 'rotary_membership_id': str(rotaryId)}
                    else:
                        partner_vals = {'rotary_club_id': rotary_club_id}
                    user.partner_id.write(partner_vals)
                except Exception:
                    _logger.warning("Could not write partner club/rotary fields for user %s", user.id)

                # Assign Members role if present
                role = env['res.users.role'].search([('name', '=', 'Members')], limit=1)
                env['res.users.role.line'].search([('user_id', '=', user.id)]).unlink()
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
                        _logger.warning("Could not set groups from roles for user %s", user.id)

                # Optionally set program_type on partner if provided (template posts program_type_id)
                program_type_id = qcontext.get('program_type_id')
                if program_type_id:
                    try:
                        user.partner_id.sudo().write({'program_type_id': int(program_type_id)})
                    except Exception:
                        _logger.warning("SIGNUP: could not set program_type_id on partner %s", user.partner_id.id)

                return request.render('rotary_signup.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                _logger.exception("Signup member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('rotary_signup.signup', qcontext)

    def get_auth_signup_qcontext(self):
        """Collect whitelisted request params and populate from signup token if present"""
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
