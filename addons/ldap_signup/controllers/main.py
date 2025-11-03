# -*- coding: utf-8 -*-
import logging
import werkzeug
import random
from datetime import date

from odoo import api, http, SUPERUSER_ID, tools, _
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController

_logger = logging.getLogger(__name__)

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}


class RotarySignupController(AuthSignupController):
    """Controller for handling Rotary member and non-member signups."""

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        """Display 'Are you a member?' selection page."""
        qcontext = self.get_auth_signup_qcontext()
        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])
        return http.request.render('ldap_reset_password.signup_is_member', qcontext)

    # ---------------- NON-MEMBER SIGNUP ----------------
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
                    resp = request.render('ldap_reset_password.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = str(generate_random_number(5, 8))
                    login = sn + rotaryId
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

                    user_id, existing_user = ldap_rec._get_or_create_user_tuple(ldap_rec, qcontext['email'], (dn, attrs))
                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error', {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int) and user_id:
                        dn_exist, entry_exist = ldap_rec._ldap_find_by_attrs(ldap_rec, attrs)
                        if not entry_exist:
                            created, message = ldap_rec._create_ldap_user(ldap_rec, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return http.request.render('ldap_reset_password.web_error', {'message': (message or '') + '.'})

                        user = request.env['res.users'].sudo().browse(user_id)
                        role = env['res.users.role'].search([('name', '=', 'Guests')])
                        if rotaryId.isdigit():
                            user.partner_id.write({'rotary_membership_id': str(rotaryId)})

                        env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                        if role:
                            env['res.users.role.line'].create({
                                'user_id': user.id,
                                'role_id': role.id,
                                'date_from': date.today(),
                                'date_to': date(2099, 12, 31)
                            })
                            user.set_groups_from_roles()

                        program_type_id = qcontext.get('program_type_id')
                        if program_type_id:
                            try:
                                user.partner_id.sudo().write({'program_type_id': int(program_type_id)})
                            except Exception:
                                _logger.warning("SIGNUP: could not set program_type_id on partner %s", user.partner_id.id)

                        return http.request.render('ldap_reset_password.web_thanks', {'message': f'You have created user: {user.login}'})
                    else:
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))
            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        resp = request.render('ldap_reset_password.signup_non_member', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    # ---------------- MEMBER SIGNUP ----------------
    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
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
                    resp = request.render('ldap_reset_password.signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = qcontext['rotary_id']
                    login = sn + rotaryId
                    cn = f"{fn} {sn}"
                    dn = f"uid={login}, {ldap_rec.ldap_base}"
                    rotary_club_id = int(qcontext['rotary_club_id'])

                    attrs = {
                        "uid": [login.encode()],
                        "givenname": [fn.encode()],
                        "cn": [cn.encode()],
                        "sn": [sn.encode()],
                        "ou": [str(rotary_club_id).encode()],
                        "employeeNumber": [qcontext['rotary_id'].encode()],
                        "mail": [qcontext['email'].encode()],
                        "userPassword": [qcontext['password'].encode()],
                        "objectclass": [b"top", b"inetOrgPerson"],
                    }

                    user_id, existing_user = ldap_rec._get_or_create_user_tuple(ldap_rec, qcontext['email'], (dn, attrs))
                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error', {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int) and user_id:
                        dn_exist, entry_exist = ldap_rec._ldap_find_by_attrs(ldap_rec, attrs)
                        if not entry_exist:
                            created, message = ldap_rec._create_ldap_user(ldap_rec, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return http.request.render('ldap_reset_password.web_error', {'message': (message or '') + '.'})

                        user = request.env['res.users'].sudo().browse(user_id)
                        if rotaryId.isdigit():
                            user.partner_id.write({
                                'rotary_club_id': rotary_club_id,
                                'rotary_membership_id': str(rotaryId)
                            })
                        else:
                            user.partner_id.write({'rotary_club_id': rotary_club_id})

                        role = env['res.users.role'].search([('name', '=', 'Members')])
                        env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                        if role:
                            env['res.users.role.line'].create({
                                'user_id': user.id,
                                'role_id': role.id,
                                'date_from': date.today(),
                                'date_to': date(2099, 12, 31)
                            })
                            user.set_groups_from_roles()

                        program_type_id = qcontext.get('program_type_id')
                        if program_type_id:
                            try:
                                user.partner_id.sudo().write({'program_type_id': int(program_type_id)})
                            except Exception:
                                _logger.warning("SIGNUP: could not set program_type_id on partner %s", user.partner_id.id)

                        return http.request.render('ldap_reset_password.web_thanks', {'message': f'You have created user: {user.login}'})
                    else:
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))
            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        resp = request.render('ldap_reset_password.signup', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    # --------------- Shared helpers ---------------
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


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

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
