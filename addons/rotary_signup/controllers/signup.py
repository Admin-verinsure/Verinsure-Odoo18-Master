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
    """Return simple objects with id and name for QWeb rendering."""
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
    """Idempotent partner lookup/create by LDAP attrs."""
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
    return P.create(vals)


# -----------------------------
# Signup Controller
# -----------------------------
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController


class LDAPSignupController(AuthSignupController):
    """Signup controller subclass for member/non-member signup using ldap_reset_password templates."""

    # ---------------------------
    # Dynamic club lookup route
    # ---------------------------
    @http.route('/clubs/by_program', type='json', auth='public', csrf=False, website=True)
    def clubs_by_program(self, program_type=None, **kw):
        """Return clubs filtered by selected program type."""
        if not program_type:
            return []
        domain = [
            ('is_rotary_club', '=', True),
            ('club_type', '=', program_type),
        ]
        clubs = request.env['res.partner'].sudo().search_read(domain, ['id', 'club_name'], order='club_name')
        return clubs

    # ---------------------------
    # Step 1 – Choose Member Type
    # ---------------------------
    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        """Landing page: choose member/non-member."""
        qcontext = self.get_auth_signup_qcontext()
        return request.render('ldap_reset_password.signup_is_member', qcontext)

    # ---------------------------
    # Step 2 – Non-Member Signup
    # ---------------------------
    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext['program_types'] = []
        qcontext['clubs'] = []

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                sn = qcontext.get('last_name', '')
                fn = qcontext.get('first_name', '')
                rotaryId = str(generate_random_number(5, 8))
                login = f"{sn}{rotaryId}"
                cn = f"{fn} {sn}"

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

                if rotaryId.isdigit():
                    user.partner_id.write({'rotary_membership_id': str(rotaryId)})

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
                _logger.exception("Signup non-member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('ldap_reset_password.signup_non_member', qcontext)

    # ---------------------------
    # Step 3 – Member Signup
    # ---------------------------
    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()

        # Static program types (old behavior)
        qcontext['program_types'] = _program_type_objects()

        # Load all rotary clubs initially (will be filtered dynamically by JS)
        qcontext['clubs'] = request.env['res.partner'].sudo().search([('is_rotary_club', '=', True)])

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup', qcontext)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup', qcontext)

                sn = qcontext.get('last_name', '')
                fn = qcontext.get('first_name', '')
                rotaryId = qcontext.get('rotary_id') or ""
                login = f"{sn}{rotaryId}"
                cn = f"{fn} {sn}"
                rotary_club_id = int(qcontext.get('rotary_club_id', 0) or 0)

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

                vals = {'rotary_club_id': rotary_club_id}
                if rotaryId.isdigit():
                    vals['rotary_membership_id'] = rotaryId
                program_type_id = qcontext.get('program_type_id')
                if program_type_id:
                    vals['program_type'] = program_type_id
                user.partner_id.write(vals)

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
