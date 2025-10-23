# -*- coding: utf-8 -*-
import logging
import random
from datetime import date

from odoo import http, api, SUPERUSER_ID, _
from odoo.http import request
import werkzeug

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers (same behavior as before)
# ---------------------------------------------------------------------------

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id'
}

def _email_is_valid(email):
    from odoo import tools
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

def generate_random_number(min_length, max_length):
    return random.randint(10 ** (min_length - 1), (10 ** max_length) - 1)

# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class LDAPSignupController(http.Controller):

    # Mirror previous combined-module behavior
    def get_auth_signup_qcontext(self):
        qcontext = {k: v for (k, v) in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}

        # Bring in auth_signup config
        qcontext.update(request.env['auth_signup.res_users'].sudo().get_auth_signup_config())

        # Token handling (standard)
        if not qcontext.get('token') and request.session.get('auth_signup_token'):
            qcontext['token'] = request.session.get('auth_signup_token')
        if qcontext.get('token'):
            try:
                for k, v in request.env['res.partner'].sudo().signup_retrieve_info(qcontext.get('token')).items():
                    qcontext.setdefault(k, v)
            except Exception:
                qcontext['error'] = _("Invalid signup token")
                qcontext['invalid_token'] = True

        # Provide clubs list for the member form (same idea as before)
        try:
            partners_with_club = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
            qcontext['clubs'] = [p for p in partners_with_club if p.club_name]
        except Exception as e:
            _logger.warning("LDAP_SIGNUP: could not prepare clubs list: %s", e)
            qcontext['clubs'] = []

        return qcontext

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        # New namespaced template id
        return request.render('ldap_signup.ldap_signup_signup_is_member')

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        # POST branch
        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                # Confirm password check
                pwd = (qcontext.get('password') or "").strip()
                cpw = (qcontext.get('confirm_password') or "").strip()
                if pwd != cpw:
                    qcontext['error'] = _("Passwords do not match.")
                    resp = request.render('ldap_signup.ldap_signup_signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                env = api.Environment(request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_signup.ldap_signup_signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = (qcontext['last_name'] or '').strip()
                    fn = (qcontext['first_name'] or '').strip()
                    rotaryId = str(generate_random_number(5, 8))
                    login = f"{sn}{rotaryId}"
                    cn = f"{fn} {sn}".strip()
                    dn = f"uid={login}, {ldap_rec.ldap_base}"

                    attrs = {
                        "uid": [login.encode()],
                        "givenname": [fn.encode()],
                        "cn": [cn.encode()],
                        "sn": [sn.encode()],
                        "employeeNumber": [rotaryId.encode()],
                        "mail": [qcontext['email'].encode()],
                        "userPassword": [pwd.encode()],
                        "objectclass": [b"top", b"inetOrgPerson"],
                    }

                    user_id, existing_user = ldap_rec._get_or_create_user_tuple(ldap_rec, qcontext['email'], (dn, attrs))
                    if existing_user:
                        return request.render('ldap_signup.ldap_signup_web_error', {'message': _('Error: User already exists.')})

                    if isinstance(user_id, int) and user_id:
                        user = request.env['res.users'].sudo().browse(user_id)

                        # Roles (same logic as before)
                        try:
                            role = env['res.users.role'].search([('name', '=', 'Guests')])
                            if rotaryId.isdigit():
                                user.partner_id.write({'rotary_membership_id': str(rotaryId)})

                            env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                            if role:
                                env['res.users.role.line'].create({
                                    'user_id': user.id,
                                    'role_id': role.id,
                                    'date_from': date.today(),
                                    'date_to': date(2099, 12, 31),
                                })
                                user.set_groups_from_roles()
                        except Exception as e:
                            _logger.warning("LDAP_SIGNUP: could not assign Guest role: %s", e)

                        return request.render('ldap_signup.ldap_signup_web_thanks', {'message': _('You have created user: %s') % user.login})

                    # Fallback error if user_id not int
                    qcontext['error'] = _("Could not create a new account. %s") % str(user_id)
                else:
                    qcontext['error'] = _("No LDAP configuration found.")
            except Exception as e:
                _logger.error("LDAP_SIGNUP (guest) failed: %s", e, exc_info=True)
                qcontext['error'] = _("Could not create account.")

        # GET or error redisplay
        resp = request.render('ldap_signup.ldap_signup_signup_non_member', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        # POST branch
        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                # Confirm password check
                pwd = (qcontext.get('password') or "").strip()
                cpw = (qcontext.get('confirm_password') or "").strip()
                if pwd != cpw:
                    qcontext['error'] = _("Passwords do not match.")
                    resp = request.render('ldap_signup.ldap_signup_signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                env = api.Environment(request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_signup.ldap_signup_signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = (qcontext['last_name'] or '').strip()
                    fn = (qcontext['first_name'] or '').strip()
                    rotaryId = (qcontext.get('rotary_id') or '').strip()
                    login = f"{sn}{rotaryId}"
                    cn = f"{fn} {sn}".strip()
                    dn = f"uid={login}, {ldap_rec.ldap_base}"

                    # club id (defensive cast)
                    try:
                        rotary_club_id = int(qcontext.get('rotary_club_id') or 0)
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
                        "userPassword": [pwd.encode()],
                        "objectclass": [b"top", b"inetOrgPerson"],
                    }

                    user_id, existing_user = ldap_rec._get_or_create_user_tuple(ldap_rec, qcontext['email'], (dn, attrs))
                    if existing_user:
                        return request.render('ldap_signup.ldap_signup_web_error', {'message': _('Error: User already exists.')})

                    if isinstance(user_id, int) and user_id:
                        user = request.env['res.users'].sudo().browse(user_id)

                        # Write partner fields as before
                        try:
                            if str(rotaryId).isdigit():
                                user.partner_id.write({'rotary_club_id': rotary_club_id, 'rotary_membership_id': str(rotaryId)})
                            else:
                                user.partner_id.write({'rotary_club_id': rotary_club_id})
                        except Exception as e:
                            _logger.warning("LDAP_SIGNUP: could not write partner club fields: %s", e)

                        # Assign 'Members' role as before
                        try:
                            role = env['res.users.role'].search([('name', '=', 'Members')])
                            env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                            if role:
                                env['res.users.role.line'].create({
                                    'user_id': user.id,
                                    'role_id': role.id,
                                    'date_from': date.today(),
                                    'date_to': date(2099, 12, 31),
                                })
                                user.set_groups_from_roles()
                        except Exception as e:
                            _logger.warning("LDAP_SIGNUP: could not assign Members role: %s", e)

                        return request.render('ldap_signup.ldap_signup_web_thanks', {'message': _('You have created user: %s') % user.login})

                    # Fallback error if user_id not int
                    qcontext['error'] = _("Could not create a new account. %s") % str(user_id)
                else:
                    qcontext['error'] = _("No LDAP configuration found.")
            except Exception as e:
                _logger.error("LDAP_SIGNUP (member) failed: %s", e, exc_info=True)
                qcontext['error'] = _("Could not create account.")

        # GET or error redisplay
        resp = request.render('ldap_signup.ldap_signup_signup', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp
