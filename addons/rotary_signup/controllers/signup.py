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

# Try lazy import of python-ldap to avoid import-time crash if missing.
try:
    import ldap
    import ldap.modlist as modlist
except Exception:
    ldap = None
    modlist = None
    _logger.debug("python-ldap not available at import time; LDAP operations will be disabled")

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

_PROGRAM_TYPE_NAMES = ["None", "Rotary", "Rotaract", "Interact", "Rota-Kids"]


def _program_type_objects():
    """Return lightweight mock objects for static program type dropdown."""
    return [{'id': i, 'name': n} for i, n in enumerate(_PROGRAM_TYPE_NAMES, start=1)]


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
    if env['res.users'].with_context(active_test=False).search([('email', 'ilike', email)], limit=1):
        return False, _("This email is already registered.")
    if not (first_name or "").strip():
        return False, _("First name is required.")
    if not (last_name or "").strip():
        return False, _("Last name is required.")
    return True, ""


def ensure_partner_from_ldap(env, attrs, company_id):
    """Ensure partner record exists for given LDAP attributes (idempotent)."""
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


# -----------------------------
# Signup Controller
# -----------------------------
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController


class LDAPSignupController(AuthSignupController):
    """Signup flow using ldap_reset_password templates."""

    @http.route('/clubs/by_program', type='json', auth='public', csrf=False, website=True)
    def clubs_by_program(self, program_type=None, **kw):
        if not program_type:
            return []
        try:
            env = request.env['res.partner'].sudo()
            domain = [('active', '=', True)]
            if str(program_type).isdigit():
                domain.append(('program_type_id', '=', int(program_type)))
            else:
                domain.append(('club_type', '=', program_type))
            clubs = env.search_read(domain, ['id', 'club_name', 'name'], order='club_name')
            return [{'id': c['id'], 'name': c.get('club_name') or c['name']} for c in clubs]
        except Exception as e:
            request.env.cr.rollback()
            _logger.exception("Club lookup error: %s", e)
            return []

    # --- Step 1 ---
    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        qcontext = self.get_auth_signup_qcontext()
        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])
        return request.render('ldap_reset_password.signup_is_member', qcontext)

    # --- Step 2: Non-member signup ---
    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext.setdefault('program_types', [])
        qcontext.setdefault('clubs', [])

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if request.httprequest.method == 'POST':
            env = api.Environment(request.cr, SUPERUSER_ID, {})
            try:
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                ldap_conf = env['res.company.ldap'].search([], limit=1)
                if not ldap_conf:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                email = (qcontext.get('email') or '').strip().lower()
                sn = (qcontext.get('last_name') or '').strip()
                fn = (qcontext.get('first_name') or '').strip()
                cn = f"{fn} {sn}".strip()
                rotary_id = str(generate_random_number(5, 8))

                ldap_model = env['res.company.ldap'].sudo()
                dn_found, entry_found = ldap_model._ldap_find_by_attrs(ldap_conf, {'mail': [email.encode()]})

                if entry_found:
                    existing_uid = ldap_model._get_uid_from_attrs(entry_found[1]) or email
                    login = existing_uid.lower()
                    _logger.info(f"Reusing existing LDAP entry for {email} with uid={login}")
                else:
                    login = (sn + rotary_id).lower()

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "employeeNumber": [rotary_id.encode()],
                    "mail": [email.encode()],
                    "userPassword": [qcontext.get('password', '').encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                ldap_base = getattr(ldap_conf, 'ldap_base', False) or ''
                dn = f"uid={login},{ldap_base}" if ldap_base else None

                user = None
                try:
                    user_id, existing = ldap_model._get_or_create_user_tuple(ldap_conf, email, (dn, attrs))
                    if isinstance(user_id, int) and user_id:
                        user = env['res.users'].sudo().browse(user_id)
                except Exception as e:
                    _logger.debug("LDAP-backed user create failed (fall back): %s", e)
                    user = None

                partner = ensure_partner_from_ldap(env, attrs, ldap_conf.company.id if ldap_conf.company else env.company.id)
                if not user:
                    user = env['res.users'].sudo().create({'login': login, 'partner_id': partner.id, 'active': True, 'name': cn})

                if rotary_id.isdigit():
                    partner.write({'rotary_membership_id': rotary_id})

                role = env['res.users.role'].search([('name', '=', 'Guests')], limit=1)
                env['res.users.role.line'].search([('user_id', '=', user.id)]).unlink()
                if role:
                    env['res.users.role.line'].create({
                        'user_id': user.id,
                        'role_id': role.id,
                        'date_from': date.today(),
                        'date_to': date(2099, 12, 31),
                    })
                    user.set_groups_from_roles()

                return request.render('ldap_reset_password.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                env.cr.rollback()
                _logger.exception("Signup non-member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('ldap_reset_password.signup_non_member', qcontext)

    # --- Step 3: Member signup ---
    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext['program_types'] = _program_type_objects()
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if request.httprequest.method == 'POST':
            env = api.Environment(request.cr, SUPERUSER_ID, {})
            try:
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup', qcontext)

                ldap_conf = env['res.company.ldap'].search([], limit=1)
                if not ldap_conf:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup', qcontext)

                email = (qcontext.get('email') or '').strip().lower()
                sn = (qcontext.get('last_name') or '').strip()
                fn = (qcontext.get('first_name') or '').strip()
                cn = f"{fn} {sn}".strip()
                rotary_id = (qcontext.get('rotary_id') or '').strip()
                rotary_club_id = int(qcontext.get('rotary_club_id') or 0)

                ldap_model = env['res.company.ldap'].sudo()
                dn_found, entry_found = ldap_model._ldap_find_by_attrs(ldap_conf, {'mail': [email.encode()]})

                if entry_found:
                    existing_uid = ldap_model._get_uid_from_attrs(entry_found[1]) or email
                    login = existing_uid.lower()
                    _logger.info(f"Reusing existing LDAP entry for {email} with uid={login}")
                else:
                    login = (sn + (rotary_id or str(generate_random_number(5, 8)))).lower()

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "ou": [str(rotary_club_id).encode()],
                    "mail": [email.encode()],
                    "userPassword": [qcontext.get('password', '').encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }
                if rotary_id:
                    attrs['employeeNumber'] = [rotary_id.encode()]

                ldap_base = getattr(ldap_conf, 'ldap_base', False) or ''
                dn = f"uid={login},{ldap_base}" if ldap_base else None

                user = None
                try:
                    user_id, existing = ldap_model._get_or_create_user_tuple(ldap_conf, email, (dn, attrs))
                    if isinstance(user_id, int) and user_id:
                        user = env['res.users'].sudo().browse(user_id)
                except Exception as e:
                    _logger.debug("LDAP-backed create failed, will fallback: %s", e)
                    user = None

                partner = ensure_partner_from_ldap(env, attrs, ldap_conf.company.id if ldap_conf.company else env.company.id)
                if not user:
                    user = env['res.users'].sudo().create({'login': login, 'partner_id': partner.id, 'active': True, 'name': cn})

                vals = {}
                if rotary_club_id:
                    vals['rotary_club_id'] = rotary_club_id
                if rotary_id and rotary_id.isdigit():
                    vals['rotary_membership_id'] = rotary_id
                if qcontext.get('program_type_id'):
                    try:
                        vals['program_type_id'] = int(qcontext['program_type_id'])
                    except Exception:
                        vals['program_type_id'] = qcontext.get('program_type_id')
                if vals:
                    partner.write(vals)

                role = env['res.users.role'].search([('name', '=', 'Members')], limit=1)
                env['res.users.role.line'].search([('user_id', '=', user.id)]).unlink()
                if role:
                    env['res.users.role.line'].create({
                        'user_id': user.id,
                        'role_id': role.id,
                        'date_from': date.today(),
                        'date_to': date(2099, 12, 31),
                    })
                    user.set_groups_from_roles()

                return request.render('ldap_reset_password.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                env.cr.rollback()
                _logger.exception("Signup member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('ldap_reset_password.signup', qcontext)

    def get_auth_signup_qcontext(self):
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
