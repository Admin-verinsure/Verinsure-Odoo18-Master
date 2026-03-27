# -*- coding: utf-8 -*-

import ldap
import ldap.modlist as modlist

# Odoo & stdlib
import json
import logging
import urllib.request
import urllib.parse
import werkzeug
import random
import threading

from collections import defaultdict
from datetime import datetime, timedelta, date
from threading import Lock
from ldap.filter import filter_format
from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import Controller, request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController
from odoo import registry as odoo_registry

_logger = logging.getLogger(__name__)

# set True only during debugging to surface raw exceptions on the signup page
SHOW_RAW_SIGNUP_ERROR = False

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type',
    'program_type',
    'program_type_id',
}

# ---------------------------------------------------------------------------
# reCAPTCHA – In-memory rate limiter (per Odoo worker process).
# NOTE: For multi-worker setups replace with a Redis-backed or DB counter.
# ---------------------------------------------------------------------------

_rate_limit_lock = Lock()
_failed_attempts: dict = defaultdict(list)   # { ip: [datetime, …] }


def _get_client_ip() -> str:
    """Extract real client IP, honouring X-Forwarded-For (requires proxy_mode=True)."""
    forwarded_for = request.httprequest.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.httprequest.remote_addr or "unknown"


def _is_rate_limited(ip: str, max_failures: int, window_minutes: int = 60) -> bool:
    """Return True if ip has exceeded max_failures within the rolling window."""
    now    = datetime.utcnow()
    cutoff = now - timedelta(minutes=window_minutes)
    with _rate_limit_lock:
        _failed_attempts[ip] = [ts for ts in _failed_attempts[ip] if ts > cutoff]
        return len(_failed_attempts[ip]) >= max_failures


def _record_failed_captcha(ip: str) -> None:
    with _rate_limit_lock:
        _failed_attempts[ip].append(datetime.utcnow())


def _get_recaptcha_config() -> tuple:
    """
    Returns (site_key, secret_key, max_failures) from ir.config_parameter.
    Raises ValueError when keys are missing / still set to placeholder values.
    """
    ICP        = request.env["ir.config_parameter"].sudo()
    site_key   = ICP.get_param("recaptcha.site_key",   default="")
    secret_key = ICP.get_param("recaptcha.secret_key", default="")
    max_fail   = int(ICP.get_param("recaptcha.max_failures_per_hour", default="5"))

    if not site_key or not secret_key \
            or "REPLACE_WITH" in site_key or "REPLACE_WITH" in secret_key:
        raise ValueError(
            "reCAPTCHA keys not configured. "
            "Set recaptcha.site_key and recaptcha.secret_key in "
            "Settings > Technical > System Parameters."
        )
    return site_key, secret_key, max_fail


def _verify_recaptcha(token: str, secret_key: str, client_ip: str) -> tuple:
    """
    Verify a reCAPTCHA v2 response token against Google's siteverify API.
    Returns (success: bool, error_message: str).
    Fails CLOSED on network/timeout errors.
    """
    if not (token or "").strip():
        return False, _("Please complete the CAPTCHA verification.")

    payload = urllib.parse.urlencode({
        "secret":   secret_key,
        "response": token.strip(),
        "remoteip": client_ip,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://www.google.com/recaptcha/api/siteverify",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        _logger.error(
            "reCAPTCHA HTTP request failed | IP: %s | error: %s", client_ip, exc,
        )
        return False, _(
            "CAPTCHA verification service is unavailable. Please try again later."
        )

    if result.get("success"):
        return True, ""

    _logger.warning(
        "reCAPTCHA FAILED | IP: %s | error-codes: %s",
        client_ip, result.get("error-codes", []),
    )
    return False, _("CAPTCHA verification failed. Please try again.")


def _captcha_gate(post: dict, client_ip: str) -> tuple:
    """
    Full CAPTCHA pipeline: load keys → rate-limit → verify token.
    Returns (passed: bool, error_message: str, site_key: str).
    """
    try:
        site_key, secret_key, max_fail = _get_recaptcha_config()
    except ValueError as exc:
        _logger.error("reCAPTCHA config error | IP: %s | %s", client_ip, exc)
        return False, _("Signup is temporarily unavailable. Please contact support."), ""

    if _is_rate_limited(client_ip, max_fail):
        _logger.warning(
            "SIGNUP RATE LIMITED | IP: %s | exceeded %d failures/hour",
            client_ip, max_fail,
        )
        return False, _(
            "Too many failed attempts from your network. Please try again later."
        ), site_key

    token      = post.get("g-recaptcha-response", "")
    ok, msg    = _verify_recaptcha(token, secret_key, client_ip)
    if not ok:
        _record_failed_captcha(client_ip)
        _logger.warning(
            "CAPTCHA FAILED | IP: %s | reason: %s | first: %s | last: %s | email: %s",
            client_ip, msg,
            post.get("first_name", ""),
            post.get("last_name", ""),
            post.get("email", ""),
        )
        return False, msg, site_key

    return True, "", site_key


# ---------------------------------------------------------------------------
# Async mail helper – UNCHANGED
# ---------------------------------------------------------------------------

def _kick_async_mail_send(db_name: str):
    def _runner():
        try:
            with api.Environment.manage():
                with odoo_registry(db_name).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    try:
                        if hasattr(env['mail.mail'], 'process_email_queue'):
                            env['mail.mail'].sudo().process_email_queue()
                        elif hasattr(env['mail.mail'], '_process_queue'):
                            env['mail.mail'].sudo()._process_queue()
                        else:
                            _logger.warning("PWRESET: mail queue process method not found")
                    except Exception as e:
                        _logger.warning("PWRESET: async mail queue failed: %s", e)
                    cr.commit()
        except Exception as e:
            _logger.warning("PWRESET: async sender thread crashed: %s", e)

    th = threading.Thread(target=_runner, name="otp-mail-sender", daemon=True)
    try:
        th.start()
    except Exception as e:
        _logger.warning("PWRESET: could not start async sender: %s", e)


# ---------------------------------------------------------------------------
# Models – UNCHANGED
# ---------------------------------------------------------------------------

class ResPartner(models.Model):
    _inherit = 'res.partner'
    rotary_membership_id = fields.Char(string="Rotary ID")


class ChangePasswordWizard(models.TransientModel):
    _name        = 'change.password.wizard'
    _inherit     = 'change.password.wizard'
    _description = "Change Password Wizard"

    def _default_user_ids(self):
        user_ids = self._context.get('active_model') == 'res.users' and self._context.get('active_ids') or []
        return [(0, 0, {'user_id': u.id, 'user_login': u.login}) for u in self.env['res.users'].browse(user_ids)]

    user_ids = fields.One2many('change.password.user', 'wizard_id', string='Users', default=_default_user_ids)

    def change_password_button(self):
        self.ensure_one()
        self.user_ids.change_password_button()
        if self.env.user in self.user_ids.user_id:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return {'type': 'ir.actions.act_window_close'}


class ChangePasswordUser(models.TransientModel):
    _name        = 'change.password.user'
    _inherit     = 'change.password.user'
    _description = "User, Change Password LDAP"

    wizard_id  = fields.Many2one('change.password.wizard', string='Wizard', required=True, ondelete='cascade')
    user_id    = fields.Many2one('res.users',              string='User',   required=True, ondelete='cascade')
    user_login = fields.Char(string='User Login', readonly=True)
    new_passwd = fields.Char(string='New Password', default='')

    def change_password_button(self):
        user       = self.user_id
        username   = str(user.login)
        new_passwd = self.new_passwd
        if not new_passwd:
            raise UserError(_("Before clicking on 'Change Password', you have to write a new password."))
        env      = api.Environment(http.request.cr, SUPERUSER_ID, {})
        ldap_rec = env['res.company.ldap'].search([], limit=1)
        if not ldap_rec:
            raise UserError('No LDAP Configuration found.')
        changed, message = ldap_rec._change_password_admin_exceptions(ldap_rec, username, new_passwd)
        if not changed:
            raise UserError(message or _("Password change failed."))
        user.password = ''
        user._set_password()
        return {'type': 'ir.actions.act_window_close'}


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------

class LDAPResetController(http.Controller):
    """LDAP password reset – UNCHANGED."""

    @http.route('/web/reset_ldap_password', type='http', auth='public', website=True, csrf=False)
    def reset_ldap_password(self, **kwargs):
        if kwargs.get('otp') and kwargs.get('login') and kwargs.get('new_password') and kwargs.get('confirm_password'):
            otp_code         = kwargs.get('otp')
            username         = kwargs.get('login')
            new_password     = kwargs.get('new_password')
            confirm_password = kwargs.get('confirm_password')
            values           = {'login': username}
            if new_password != confirm_password:
                values['password_error'] = "Passwords do not match!"
                return http.request.render('ldap_reset_password.template_otp_entry', values)
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            try:
                otp = env['otp'].search([('otp_code', '=', otp_code)], limit=1)
                if not otp:
                    values['error_message'] = "One Time Password not found!"
                    return http.request.render('ldap_reset_password.template_otp_entry', values)
                if otp.expiration_time < datetime.now() - timedelta(minutes=15):
                    values['error_message'] = "One Time Password has expired!"
                    return http.request.render('ldap_reset_password.template_otp_entry', values)
                user = env['res.users'].search([('login', '=', username)], limit=1)
                if not user or otp.user_id.id != user.id:
                    values['error_message'] = "User not found or One Time Password mismatch!"
                    return http.request.render('ldap_reset_password.template_otp_entry', values)
                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    values['error_message'] = "No LDAP Configuration. Please contact a System administrator."
                    return http.request.render('ldap_reset_password.template_otp_entry', values)
                changed, message = ldap_rec._change_password_admin_exceptions(ldap_rec, username, new_password)
                if not changed:
                    values['error_message'] = "Password reset has failed for: " + username + "."
                    return http.request.render('ldap_reset_password.template_otp_entry', values)
                user.password = ''
                user.sudo()._set_password()
                return http.request.render('ldap_reset_password.portal_thanks', {
                    'message': 'Password reset has succeeded for {}'.format(username)
                })
            except Exception as e:
                values['error_message'] = f"An error occurred: {e}"
                return http.request.render('ldap_reset_password.template_otp_entry', values)

        if kwargs.get('login'):
            username      = kwargs.get('login')
            env           = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user          = env['res.users'].search([('login', '=', username)], limit=1)
            administrator = env['res.users'].search([], limit=1, order='id')
            if user:
                if user.partner_id.email:
                    try:
                        user.sudo().action_reset_password()
                    except Exception as e:
                        _logger.warning("PWRESET: action_reset_password failed: %s", e)
                    return http.request.render('ldap_reset_password.template_otp_entry', {'login': username})
                return http.request.render('ldap_reset_password.template_contact_admin')
            return http.request.render('ldap_reset_password.template_invalid_login')

        return http.request.render('ldap_reset_password.template_otp', {'message': 'Placeholder'})

    @http.route('/web/reset_password', type='http', auth="public", website=True)
    def reset_password(self):
        return request.redirect('/web/reset_ldap_password')


class LDAPSignupController(AuthSignupController):
    """
    Rotary signup controller with reCAPTCHA v2 checkpoint.
    Every POST flow runs _captcha_gate() before any LDAP/business logic.
    All original member/non-member behaviour is preserved exactly.
    """

    @staticmethod
    def _get_site_key_safe() -> str:
        """Return site key for template rendering, or '' if not yet configured."""
        try:
            site_key, _, _ = _get_recaptcha_config()
            return site_key
        except ValueError:
            return ""

    # ------------------------------------------------------------------
    # /web/is_member  (no form POST, no CAPTCHA needed)
    # ------------------------------------------------------------------
    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        qcontext = self.get_auth_signup_qcontext()
        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])
        return http.request.render('ldap_reset_password.signup_is_member', qcontext)

    # ------------------------------------------------------------------
    # /web/signup_non_member
    # ------------------------------------------------------------------
    @http.route(
        '/web/signup_non_member',
        type='http', auth='public', website=True, sitemap=False, csrf=False,
    )
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        qcontext['recaptcha_site_key'] = self._get_site_key_safe()

        try:
            qcontext.setdefault('program_types', request.env['program.type'].sudo().search([], order='name'))
        except Exception:
            qcontext.setdefault('program_types', request.env['ir.model'].sudo().browse([]))

        if 'error' not in qcontext and request.httprequest.method == 'POST':

            # ── CAPTCHA gate ─────────────────────────────────────────
            client_ip  = _get_client_ip()
            ok, msg, sk = _captcha_gate(request.params, client_ip)
            if sk:
                qcontext['recaptcha_site_key'] = sk
            if not ok:
                qcontext['error'] = msg
                resp = request.render('ldap_reset_password.signup_non_member', qcontext)
                resp.headers['X-Frame-Options'] = 'DENY'
                return resp
            # ── END CAPTCHA gate ─────────────────────────────────────

            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok2, msg2 = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok2:
                    qcontext['error'] = msg2
                    resp = request.render('ldap_reset_password.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = qcontext['last_name']; fn = qcontext['first_name']
                    rotaryId = str(generate_random_number(5, 8))
                    login    = sn + rotaryId
                    cn       = f"{fn} {sn}"
                    dn       = f"uid={login}, {ldap_rec.ldap_base}"

                    attrs = {
                        "uid":            [login.encode()],
                        "givenname":      [fn.encode()],
                        "cn":             [cn.encode()],
                        "sn":             [sn.encode()],
                        "employeeNumber": [rotaryId.encode()],
                        "mail":           [qcontext['email'].encode()],
                        "userPassword":   [qcontext['password'].encode()],
                        "objectclass":    [b"top", b"inetOrgPerson"],
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
                                'user_id':   user.id,
                                'role_id':   role.id,
                                'date_from': date.today(),
                                'date_to':   date(2099, 12, 31),
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
                qcontext['error'] = _("Could not create account. " + (tools.ustr(e) if SHOW_RAW_SIGNUP_ERROR else ""))

        resp = request.render('ldap_reset_password.signup_non_member', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    # ------------------------------------------------------------------
    # /web/signup  (member)
    # ------------------------------------------------------------------
    @http.route(
        '/web/signup',
        type='http', auth='public', website=True, sitemap=False, csrf=False,
    )
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        qcontext['recaptcha_site_key'] = self._get_site_key_safe()

        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':

            # ── CAPTCHA gate ─────────────────────────────────────────
            client_ip    = _get_client_ip()
            ok, msg, sk  = _captcha_gate(request.params, client_ip)
            if sk:
                qcontext['recaptcha_site_key'] = sk
            if not ok:
                qcontext['error'] = msg
                resp = request.render('ldap_reset_password.signup', qcontext)
                resp.headers['X-Frame-Options'] = 'DENY'
                return resp
            # ── END CAPTCHA gate ─────────────────────────────────────

            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok2, msg2 = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok2:
                    qcontext['error'] = msg2
                    resp = request.render('ldap_reset_password.signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = qcontext['last_name']; fn = qcontext['first_name']
                    rotaryId       = qcontext['rotary_id']
                    login          = sn + rotaryId
                    cn             = f"{fn} {sn}"
                    dn             = f"uid={login}, {ldap_rec.ldap_base}"
                    rotary_club_id = int(qcontext['rotary_club_id'])

                    attrs = {
                        "uid":            [login.encode()],
                        "givenname":      [fn.encode()],
                        "cn":             [cn.encode()],
                        "sn":             [sn.encode()],
                        "ou":             [str(rotary_club_id).encode()],
                        "employeeNumber": [qcontext['rotary_id'].encode()],
                        "mail":           [qcontext['email'].encode()],
                        "userPassword":   [qcontext['password'].encode()],
                        "objectclass":    [b"top", b"inetOrgPerson"],
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
                            user.partner_id.write({'rotary_club_id': rotary_club_id, 'rotary_membership_id': str(rotaryId)})
                        else:
                            user.partner_id.write({'rotary_club_id': rotary_club_id})

                        role = env['res.users.role'].search([('name', '=', 'Members')])
                        env['res.users.role.line'].search([('user_id', '=', user_id)]).unlink()
                        if role:
                            env['res.users.role.line'].create({
                                'user_id':   user.id,
                                'role_id':   role.id,
                                'date_from': date.today(),
                                'date_to':   date(2099, 12, 31),
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
                qcontext['error'] = _("Could not create account. " + (tools.ustr(e) if SHOW_RAW_SIGNUP_ERROR else ""))

        resp = request.render('ldap_reset_password.signup', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

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
# Utilities – UNCHANGED
# ---------------------------------------------------------------------------

def extract_rotary_id(login, last_name):
    login     = (login or '').lower()
    last_name = (last_name or '').lower()
    potential  = login.replace(last_name, '')
    return potential if potential.isdigit() and 5 <= len(potential) <= 8 else None

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
    def _attr(a, key, default=""):
        try:
            vals = a.get(key) or []
            if not vals: return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    email      = (_attr(attrs, 'mail') or "").strip()
    email_norm = email.lower()
    cn         = (_attr(attrs, 'cn') or "").strip()
    given      = (_attr(attrs, 'givenname') or "").strip()
    sn         = (_attr(attrs, 'sn') or "").strip()
    name       = cn or (f"{given} {sn}".strip()) or "New Contact"
    P          = env['res.partner'].with_context(active_test=False).sudo()

    partner = False
    if email:
        partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
        if not partner:
            try:
                env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email_norm,))
                r = env.cr.fetchone()
                if r: partner = P.browse(r[0])
            except Exception:
                pass
    if not partner and cn:
        partner = P.search([('name', '=', cn)], limit=1)
    if not partner and (given or sn):
        nm = f"{given} {sn}".strip()
        if nm: partner = P.search([('name', '=', nm)], limit=1)

    if partner:
        updates = {}
        if email and (partner.email or "").strip().lower() != email_norm:
            updates['email'] = email
        if company_id and partner.company_id.id != company_id:
            updates['company_id'] = company_id
        if updates: partner.write(updates)
        return partner

    vals = {'name': name}
    if email:      vals['email']      = email
    if company_id: vals['company_id'] = company_id

    try:
        return P.create(vals)
    except ValidationError as ve:
        msg = tools.ustr(ve).lower()
        if 'already used' in msg or ('unique' in msg and 'email' in msg):
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if not p and email:
                try:
                    env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email_norm,))
                    r = env.cr.fetchone()
                    if r: p = P.browse(r[0])
                except Exception:
                    pass
            if p: return p
        raise
    except Exception as e:
        msg = tools.ustr(e).lower()
        if 'unique' in msg and 'email' in msg:
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if p: return p
        raise


# ---------------------------------------------------------------------------
# LDAP model (override) – UNCHANGED
# ---------------------------------------------------------------------------

class CompanyLDAP(models.Model):
    _inherit = 'res.company.ldap'

    def _pyldap_connect(self, conf):
        host    = getattr(conf, "ldap_server", None) or (conf.get("ldap_server") if isinstance(conf, dict) else "127.0.0.1")
        port    = int(getattr(conf, "ldap_server_port", None) or (conf.get("ldap_server_port") if isinstance(conf, dict) else 389))
        use_tls = bool(getattr(conf, "ldap_tls", None) if not isinstance(conf, dict) else conf.get("ldap_tls", False))
        scheme  = "ldaps" if port == 636 else "ldap"
        conn    = ldap.initialize(f"{scheme}://{host}:{port}")
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        for opt, val in [(ldap.OPT_NETWORK_TIMEOUT, 5), (ldap.OPT_TIMEOUT, 5), (ldap.OPT_REFERRALS, 0)]:
            try: conn.set_option(opt, val)
            except Exception: pass
        if use_tls and port != 636:
            conn.start_tls_s()
        return conn

    def _as_dict(self, conf):
        if isinstance(conf, dict): return conf
        return {
            'ldap_filter':      conf.ldap_filter,
            'ldap_base':        conf.ldap_base,
            'ldap_binddn':      conf.ldap_binddn,
            'ldap_password':    conf.ldap_password,
            'ldap_server':      conf.ldap_server,
            'ldap_server_port': conf.ldap_server_port,
            'ldap_tls':         conf.ldap_tls,
            'create_user':      conf.create_user,
            'user':             getattr(conf.user, 'id', False),
            'company':          (conf.company.id, conf.company.name) if conf.company else False,
        }

    def _get_entry(self, conf, login):
        confd = self._as_dict(conf)
        dn = entry = False
        try:
            fexpr = filter_format(confd['ldap_filter'], (login,))
        except Exception:
            _logger.warning("Could not format LDAP filter.")
            fexpr = False
        if fexpr:
            results = [r for r in self._query(confd, tools.ustr(fexpr)) if r[0]]
            for r in results:
                if len(r[1].get('uid', [])) == 1:
                    entry = r; dn = r[0]; break
        return dn, entry

    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        changed = False; message = ""
        confd   = self._as_dict(conf)
        dn, _   = self._get_entry(conf, login)
        admindn = confd['ldap_binddn']; adminpw = confd['ldap_password']

        if not dn:
            env  = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', login)], limit=1)
            if user:
                full  = (user.partner_id.name or '').strip() or login
                parts = full.split()
                fn    = parts[0] if parts else 'Default'
                sn    = parts[-1] if len(parts) > 1 else 'User'
                attrs = {
                    "uid":          [login.encode()], "givenname": [fn.encode()],
                    "cn":           [full.encode()],  "sn":        [sn.encode()],
                    "userPassword": [new_passwd.encode()],
                    "objectclass":  [b"top", b"inetOrgPerson"],
                }
                if getattr(user.partner_id, 'email', None):
                    attrs["mail"] = [user.partner_id.email.encode()]
                dn = f'uid={login}, {confd["ldap_base"]}'
                created, message = self._create_ldap_user(confd, dn, attrs)
                return (True, message) if created else (False, message)
            return False, "User not found in LDAP directory."

        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(admindn, adminpw)
            conn.passwd_s(dn, None, new_passwd)
            changed = True; message = 'Success'
            conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            message = 'An LDAP exception occurred: ' + str(e)
        except ldap.LDAPError as e:
            message = 'An LDAP exception occurred: ' + str(e)
        return changed, message

    def _ldap_attr_text(self, attrs, key, default=""):
        try:
            vals = attrs.get(key) or []
            if not vals: return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    def _get_uid_from_attrs(self, attrs):
        try:
            vals = attrs.get('uid') or []
            if not vals: return ''
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return ''

    def _ldap_find_by_attrs(self, conf, attrs):
        confd = self._as_dict(conf)
        def _q(flt):
            try: return self._query(confd, flt)
            except Exception: return []
        mail  = (self._ldap_attr_text(attrs, 'mail')      or '').strip()
        given = (self._ldap_attr_text(attrs, 'givenname') or '').strip()
        sn    = (self._ldap_attr_text(attrs, 'sn')        or '').strip()
        if not mail: return False, False
        try:
            if given and sn:
                flt = filter_format('(&(objectClass=inetOrgPerson)(mail=%s)(givenName=%s)(sn=%s))', (mail, given, sn))
            else:
                flt = filter_format('(&(objectClass=inetOrgPerson)(mail=%s))', (mail,))
            res = [r for r in _q(flt) if r and r[0]]
            if res: return res[0][0], res[0]
        except Exception:
            _logger.exception("_ldap_find_by_attrs failed")
        return False, False

    def _get_or_create_user(self, conf, login, ldap_entry):
        user_id, _ = self._get_or_create_user_tuple(conf, login, ldap_entry)
        return user_id

    def _get_or_create_user_tuple(self, conf, login, ldap_entry):
        env   = self.env
        confd = self._as_dict(conf)
        req_email = tools.ustr(login or "").strip().lower()

        env.cr.execute("SELECT id FROM res_users WHERE lower(login)=%s", (req_email,))
        row = env.cr.fetchone()
        if row: return row[0], True

        mapped_vals = self._map_ldap_attributes(conf, req_email, ldap_entry) or {}
        company_id  = mapped_vals.get('company_id') or env.company.id

        def _find_partner(a):
            def _t(key, d=""):
                try:
                    vals = a.get(key) or []
                    v    = vals[0] if vals else d
                    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
                except Exception: return d
            email = (_t('mail') or '').strip().lower()
            cn    = (_t('cn')   or '').strip()
            given = (_t('givenname') or '').strip()
            sn    = (_t('sn')   or '').strip()
            P     = env['res.partner'].with_context(active_test=False).sudo()
            if email:
                p = P.search(['|', ('email_normalized', '=', email), ('email', '=', email)], limit=1)
                if not p:
                    try:
                        env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email,))
                        rr = env.cr.fetchone()
                        if rr: p = P.browse(rr[0])
                    except Exception: pass
                if p: return p
            if cn:
                p = P.search([('name', '=', cn)], limit=1)
                if p: return p
            if given or sn:
                nm = f"{given} {sn}".strip()
                if nm:
                    p = P.search([('name', '=', nm)], limit=1)
                    if p: return p
            return False

        def _unique_login(desired):
            base = tools.ustr(desired or '').strip().lower() or "user"
            U    = env['res.users'].with_context(active_test=False).sudo()
            if not U.search([('login', '=ilike', base)], limit=1): return base
            i = 2
            while True:
                cand = f"{base}-{i}"
                if not U.search([('login', '=ilike', cand)], limit=1): return cand
                i += 1

        def _make_user(partner, desired_login):
            final = _unique_login(desired_login)
            vals  = dict(mapped_vals)
            vals.update({'login': final, 'partner_id': partner.id, 'active': True, 'totp_enabled': False})
            vals.pop('email', None)
            return env['res.users'].with_context(no_reset_password=True).sudo().create(vals).id, final

        ctrl_attrs = (ldap_entry[1] if ldap_entry else {}) or {}
        dn_found, entry_found = self._ldap_find_by_attrs(confd, ctrl_attrs)

        if not entry_found and req_email:
            try:
                probe = {'mail': [req_email.encode()]}
                if ctrl_attrs.get('givenname'): probe['givenname'] = ctrl_attrs['givenname']
                if ctrl_attrs.get('sn'):        probe['sn']        = ctrl_attrs['sn']
                dn_found, entry_found = self._ldap_find_by_attrs(confd, probe)
            except Exception: pass

        if entry_found:
            la  = entry_found[1]
            uid = (self._get_uid_from_attrs(la) or req_email).strip().lower()
            U   = env['res.users'].with_context(active_test=False).sudo()
            u   = U.search([('login', '=ilike', uid)], limit=1)
            if u and u.active: return u.id, True
            partner = _find_partner(la) or ensure_partner_from_ldap(env, la, company_id)
            user_id, _ = _make_user(partner, uid)
            return user_id, False

        dn_p, attrs_p = ldap_entry or (None, None)
        if not dn_p or not isinstance(attrs_p, dict): return 0, False
        created, msg = self._create_ldap_user(confd, dn_p, attrs_p)
        if not created:
            _logger.warning("LDAP create failed: %s", msg)
            return 0, False
        new_uid = (self._get_uid_from_attrs(attrs_p) or req_email).strip().lower()
        partner = _find_partner(attrs_p) or ensure_partner_from_ldap(env, attrs_p, company_id)
        user_id, _ = _make_user(partner, new_uid)
        return user_id, False

    def _create_ldap_user(self, conf, user_dn, attributes):
        created = False; message = ""
        confd   = self._as_dict(conf)
        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(confd['ldap_binddn'], confd['ldap_password'])
            conn.add_s(user_dn, modlist.addModlist(attributes))
            created = True; message = 'Success'
            conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            message = 'An LDAP exception occurred: ' + str(e)
        except ldap.LDAPError as e:
            if e.args and isinstance(e.args[0], dict) and e.args[0].get('desc') == 'Already exists':
                message = 'The LDAP entry already exists: ' + str(e)
            else:
                message = 'An LDAP exception occurred: ' + str(e)
        return created, message

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        values     = super()._map_ldap_attributes(conf, login, ldap_entry) or {}
        company_id = False
        if isinstance(conf, dict):
            v = conf.get('company')
            if isinstance(v, (list, tuple)) and v: company_id = v[0]
            elif isinstance(v, int):               company_id = v
        else:
            try:   company_id = conf.company.id if getattr(conf, 'company', False) else False
            except: company_id = False
        values['company_id'] = company_id or self.env.company.id
        values['login']      = tools.ustr(values.get('login') or login).lower().strip()
        return values
