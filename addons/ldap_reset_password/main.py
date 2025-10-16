# -*- coding: utf-8 -*-

# Low-level python-ldap for raw LDAP operations (bind, add, passwd, etc.)
import ldap
import ldap.modlist as modlist

# Odoo & stdlib
import logging
import werkzeug
import random
import string
import json

from datetime import datetime, timedelta, date
from ldap.filter import filter_format
from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.tools.misc import str2bool
from odoo.tools.pycompat import to_text
from odoo.http import content_disposition, Controller, request, route
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController
from odoo.addons.mail.models.mail_mail import MailMail
from odoo.addons.mail.models.mail_template import MailTemplate

_logger = logging.getLogger(__name__)

# Whitelisted web parameters for signup flows
SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id'
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ResPartner(models.Model):
    _inherit = 'res.partner'
    rotary_membership_id = fields.Char(string="Rotary ID")


class ChangePasswordWizard(models.TransientModel):
    _name = 'change.password.wizard'
    _inherit = 'change.password.wizard'
    _description = "Change Password Wizard"

    def _default_user_ids(self):
        user_ids = self._context.get('active_model') == 'res.users' and self._context.get('active_ids') or []
        return [
            (0, 0, {'user_id': user.id, 'user_login': user.login})
            for user in self.env['res.users'].browse(user_ids)
        ]

    user_ids = fields.One2many('change.password.user', 'wizard_id', string='Users', default=_default_user_ids)

    def change_password_button(self):
        self.ensure_one()
        self.user_ids.change_password_button()
        if self.env.user in self.user_ids.user_id:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return {'type': 'ir.actions.act_window_close'}


class ChangePasswordUser(models.TransientModel):
    _name = 'change.password.user'
    _inherit = 'change.password.user'
    _description = "User, Change Password LDAP"

    wizard_id = fields.Many2one('change.password.wizard', string='Wizard', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    user_login = fields.Char(string='User Login', readonly=True)
    new_passwd = fields.Char(string='New Password', default='')

    def change_password_button(self):
        user_id = self.user_id
        username = str(user_id.login)
        new_passwd = self.new_passwd

        _logger.info("Calling LDAPAPI. Updating LDAP Password for %s", username)

        if not new_passwd:
            raise UserError(_("Before clicking on 'Change Password', you have to write a new password."))

        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
        ldap_records = env['res.company.ldap'].search([])
        ldap_dict = {rec.id: rec.read() for rec in ldap_records}
        ldap_config = env['res.company.ldap'].browse(next(iter(ldap_dict))) if ldap_dict else None

        if ldap_config:
            changed, message = ldap_config._change_password_admin_exceptions(ldap_config, username, new_passwd)
            if changed:
                _logger.info("Password reset has succeeded for: %s.", username)
                user_id.password = ''
                user_id._set_password()
                return {'type': 'ir.actions.act_window_close'}
            _logger.error("Password reset has failed for: %s.", username)
            raise UserError(message)

        _logger.info("No LDAP Config.")
        raise UserError('No LDAP Configuration found.')


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------

class LDAPResetController(http.Controller):

    @http.route('/web/reset_ldap_password', type='http', auth='public', website=True, csrf=False)
    def reset_ldap_password(self, **kwargs):
        # Phase 2: OTP + new pwd
        if kwargs.get('otp') and kwargs.get('login') and kwargs.get('new_password') and kwargs.get('confirm_password'):
            otp_code = kwargs.get('otp')
            username = kwargs.get('login')
            new_password = kwargs.get('new_password')
            confirm_password = kwargs.get('confirm_password')

            error_response_values = {'login': username}

            if new_password != confirm_password:
                error_response_values['password_error'] = "Passwords do not match!"
                return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            try:
                otp = env['otp'].search([('otp_code', '=', otp_code)], limit=1)
                if not otp:
                    error_response_values['error_message'] = "One Time Password not found!"
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

                if otp.expiration_time < datetime.now() - timedelta(minutes=15):
                    error_response_values['error_message'] = "One Time Password has expired!"
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

                user = env['res.users'].search([('login', '=', username)], limit=1)
                if not user or otp.user_id.id != user.id:
                    error_response_values['error_message'] = "User not found or One Time Password mismatch!"
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

                ldap_config = env['res.company.ldap'].search([], limit=1)
                if ldap_config:
                    changed, message = ldap_config._change_password_admin_exceptions(ldap_config, username, new_password)
                    if changed:
                        _logger.info("Password reset has succeeded for: %s.", username)
                        user.password = ''
                        user.sudo()._set_password()
                        return http.request.render('ldap_reset_password.portal_thanks', {
                            'message': 'Password reset has succeeded for {}'.format(username)
                        })
                    _logger.info("LDAP Server produced the following error: %s", message)
                    error_response_values['error_message'] = "Password reset has failed for: " + username + "."
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)
                else:
                    error_response_values['error_message'] = (
                        "No LDAP Configuration. Please contact a System administrator via the helpdesk."
                    )
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

            except Exception as e:
                error_response_values['error_message'] = f"An error occurred: {e}"
                return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

        # Phase 1: request OTP
        if kwargs.get('login'):
            username = kwargs.get('login')
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', username)])

            administrator = env['res.users'].search([], limit=1, order='id')
            administrator_email = administrator.partner_id.email_normalized if administrator.partner_id else ""

            if user:
                if user.partner_id.email:
                    otp_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                    expiration_time = datetime.now() + timedelta(minutes=15)
                    env['otp'].create({
                        'user_id': user.id,
                        'otp_code': otp_code,
                        'expiration_time': expiration_time,
                    })

                    website_domain = http.request.httprequest.headers.get('Host').split(':')[0]
                    subject = "One Time Password for Password Change Verification"
                    if website_domain == "localhost":
                        website_domain = "rotaryoceania.zone"
                    email_from = f"no-reply@{website_domain}"

                    mail_template = env['mail.template'].sudo().search(
                        [('name', '=', 'Reset LDAP Password Email')], limit=1
                    )
                    email_values = {'email_from': email_from}
                    custom_context = {
                        'subject': subject,
                        'otp_code': otp_code,
                        'administrator_email': administrator_email,
                        'email_from': email_from
                    }

                    mail_template.with_context(custom_context).sudo().send_mail(user.id, email_values)
                    return http.request.render('ldap_reset_password.template_otp_entry', {'login': username})
                else:
                    return http.request.render('ldap_reset_password.template_contact_admin')
            else:
                return http.request.render('ldap_reset_password.template_invalid_login')

        return http.request.render('ldap_reset_password.template_otp', {'message': 'Placeholder'})

    @http.route('/web/reset_password', type='http', auth="public", website=True)
    def reset_password(self):
        _logger.info("Redirecting to Reset LDAP Password.")
        return request.redirect('/web/reset_ldap_password')


class LDAPSignupController(AuthSignupController):

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        return http.request.render('ldap_reset_password.signup_is_member')

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(
                    env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'),
                )
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_reset_password.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_records = env['res.company.ldap'].search([])
                ldap_dict = {rec.id: rec.read() for rec in ldap_records}
                ldap_config = env['res.company.ldap'].browse(next(iter(ldap_dict))) if ldap_dict else None

                if ldap_config:
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = str(generate_random_number(5, 8))
                    login = sn + rotaryId
                    cn = f"{fn} {sn}"
                    dn = f"uid={login}, {ldap_config.ldap_base}"

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

                    ldap_entry = (dn, attrs)
                    user_id, existing_user = ldap_config._get_or_create_user(ldap_config, login, ldap_entry)
                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error',
                                                   {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
                        _logger.info('res_user created or reused. Ensuring LDAP entry for: %s', login)

                        dn_exist, entry_exist = ldap_config._ldap_find_by_attrs(ldap_config, attrs)
                        if not entry_exist:
                            created, message = ldap_config._create_ldap_user(ldap_config, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return http.request.render('ldap_reset_password.web_error',
                                                           {'message': (message or '') + '.'})

                        user = request.env['res.users'].sudo().browse(user_id)
                        role = env['res.users.role'].search([('name', '=', 'Guests')])

                        if rotaryId.isdigit():
                            user.partner_id.write({'rotary_membership_id': str(rotaryId)})

                        role_lines = env['res.users.role.line'].search([('user_id', '=', user_id)])
                        role_lines.unlink()
                        start_date = date.today()
                        end_date = date(2099, 12, 31)

                        if role:
                            env['res.users.role.line'].create({
                                'user_id': user.id,
                                'role_id': role.id,
                                'date_from': start_date,
                                'date_to': end_date
                            })
                            user.set_groups_from_roles()

                        return http.request.render('ldap_reset_password.web_thanks',
                                                   {'message': f'You have created user: {user.login}'})
                    elif isinstance(user_id, str):
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))

            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        response = request.render('ldap_reset_password.signup_non_member', qcontext)
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()

        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        clubs = [p for p in partners_club_name_not_empty if p.club_name]
        qcontext['clubs'] = clubs

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(
                    env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'),
                )
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_reset_password.signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_records = env['res.company.ldap'].search([])
                ldap_dict = {rec.id: rec.read() for rec in ldap_records}
                ldap_config = env['res.company.ldap'].browse(next(iter(ldap_dict))) if ldap_dict else None

                if ldap_config:
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = qcontext['rotary_id']
                    login = sn + rotaryId
                    cn = f"{fn} {sn}"
                    dn = f"uid={login}, {ldap_config.ldap_base}"
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

                    ldap_entry = (dn, attrs)
                    user_id, existing_user = ldap_config._get_or_create_user(ldap_config, login, ldap_entry)

                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error',
                                                   {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
                        _logger.info('res_user created or reused. Ensuring LDAP entry for: %s', login)

                        dn_exist, entry_exist = ldap_config._ldap_find_by_attrs(ldap_config, attrs)
                        if not entry_exist:
                            created, message = ldap_config._create_ldap_user(ldap_config, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return http.request.render('ldap_reset_password.web_error',
                                                           {'message': (message or '') + '.'})

                        user = request.env['res.users'].sudo().browse(user_id)

                        if rotaryId.isdigit():
                            user.partner_id.write({
                                'rotary_club_id': rotary_club_id,
                                'rotary_membership_id': str(rotaryId)
                            })
                        else:
                            user.partner_id.write({'rotary_club_id': rotary_club_id})

                        role = env['res.users.role'].search([('name', '=', 'Members')])
                        start_date = date.today()
                        end_date = date(2099, 12, 31)

                        role_lines = env['res.users.role.line'].search([('user_id', '=', user_id)])
                        role_lines.unlink()

                        if role:
                            env['res.users.role.line'].create({
                                'user_id': user.id,
                                'role_id': role.id,
                                'date_from': start_date,
                                'date_to': end_date
                            })
                            user.set_groups_from_roles()

                        return http.request.render('ldap_reset_password.web_thanks',
                                                   {'message': f'You have created user: {user.login}'})
                    elif isinstance(user_id, str):
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))

            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        response = request.render('ldap_reset_password.signup', qcontext)
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    def get_auth_signup_qcontext(self):
        qcontext = {k: v for (k, v) in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
        qcontext.update(self.get_auth_signup_config())
        if not qcontext.get('token') and request.session.get('auth_signup_token'):
            qcontext['token'] = request.session.get('auth_signup_token')
        if qcontext.get('token'):
            try:
                token_infos = request.env['res.partner'].sudo().signup_retrieve_info(qcontext.get('token'))
                for k, v in token_infos.items():
                    qcontext.setdefault(k, v)
            except Exception:
                qcontext['error'] = _("Invalid signup token")
                qcontext['invalid_token'] = True
        return qcontext


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def extract_rotary_id(login, last_name):
    login = (login or '').lower()
    last_name = (last_name or '').lower()
    potential_id = login.replace(last_name, '')
    return potential_id if potential_id.isdigit() and 5 <= len(potential_id) <= 8 else None


def get_error(e, path=''):
    for k in (path.split('.') if path else []):
        if not isinstance(e, dict):
            return None
        e = e.get(k)
    return e if isinstance(e, str) else None


def generate_random_number(min_length, max_length):
    min_value = 10 ** (min_length - 1)
    max_value = (10 ** max_length) - 1
    return random.randint(min_value, max_value)

# ---------- partner helper (module-level, NOT a model method) ----------
def ensure_partner_from_ldap(env, attrs, company_id):
    """
    Find or create a partner using LDAP attributes.
    Robust against case/normalization and concurrent creates.
    Priority: email → exact CN → givenName + sn.
    """
    def _attr_text(a, key, default=""):
        try:
            vals = a.get(key) or []
            if not vals:
                return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    email = (_attr_text(attrs, 'mail') or "").strip()
    email_norm = email.lower()
    cn = (_attr_text(attrs, 'cn') or "").strip()
    given = (_attr_text(attrs, 'givenname') or "").strip()
    sn = (_attr_text(attrs, 'sn') or "").strip()
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()

    # 1) Try by normalized email / raw email
    partner = False
    if email:
        partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
        if not partner:
            # Fallback: raw SQL on LOWER(email) in case email_normalized isn't populated
            try:
                env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1", (email_norm,))
                row = env.cr.fetchone()
                if row:
                    partner = P.browse(row[0])
            except Exception:
                pass

    # 2) Fallback by exact name
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

    # Create (with unique-email fallback)
    vals = {'name': name}
    if email:
        vals['email'] = email
    if company_id:
        vals['company_id'] = company_id

    try:
        return P.create(vals)
    except Exception as e:
        # If a unique-email constraint fires, re-read and reuse that partner
        msg = tools.ustr(e).lower()
        if 'unique' in msg and 'email' in msg:
            partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if partner:
                return partner
        raise
# ---------- END helper ----------

# ---------- validation helpers ----------
def _email_is_valid(email):
    email = (email or "").strip()
    try:
        single_email_re = getattr(tools, "single_email_re", None)
        if single_email_re:
            return bool(single_email_re.match(email))
    except Exception:
        pass
    return "@" in email and "." in email.split("@")[-1]

def _normalize_email(email):
    return (email or "").strip().lower()

def validate_signup_fields(env, email, first_name, last_name):
    """
    - Email must be valid format.
    - Block only if an *Odoo user* already uses this email (contact allowed).
    - First/Last name required.
    """
    if not email:
        return False, _("Email is required.")
    if not _email_is_valid(email):
        return False, _("Please enter a valid email address.")

    U = env['res.users'].with_context(active_test=False)
    existing_user = U.search([('email', 'ilike', email)], limit=1)
    if existing_user and existing_user.active:
        return False, _("This email is already registered as a user.")

    if not (first_name or "").strip():
        return False, _("First name is required.")
    if not (last_name or "").strip():
        return False, _("Last name is required.")

    return True, ""
# ---------- END validation ----------


# ---------------------------------------------------------------------------
# LDAP model (override)
# ---------------------------------------------------------------------------

class CompanyLDAP(models.Model):
    _name = 'res.company.ldap'
    _description = 'Company LDAP configuration'
    _inherit = 'res.company.ldap'
    _order = 'sequence'
    _rec_name = 'ldap_server'

    sequence = fields.Integer(default=10)
    company = fields.Many2one('res.company', string='Company', required=True, ondelete='cascade')
    ldap_server = fields.Char(string='LDAP Server address', required=True, default='127.0.0.1')
    ldap_server_port = fields.Integer(string='LDAP Server port', required=True, default=389)
    ldap_binddn = fields.Char('LDAP binddn')
    ldap_password = fields.Char(string='LDAP password')
    ldap_filter = fields.Char(string='LDAP filter', required=True)
    ldap_base = fields.Char(string='LDAP base', required=True)
    user = fields.Many2one('res.users', string='Template User')
    create_user = fields.Boolean(default=True)
    ldap_tls = fields.Boolean(string='Use TLS')

    def _pyldap_connect(self, conf):
        host = getattr(conf, "ldap_server", None) or (conf.get("ldap_server") if isinstance(conf, dict) else "127.0.0.1")
        port = int(getattr(conf, "ldap_server_port", None) or (conf.get("ldap_server_port") if isinstance(conf, dict) else 389))
        use_tls = bool(getattr(conf, "ldap_tls", None) if not isinstance(conf, dict) else conf.get("ldap_tls", False))

        scheme = "ldaps" if port == 636 else "ldap"
        uri = f"{scheme}://{host}:{port}"
        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        try:
            conn.set_option(ldap.OPT_REFERRALS, 0)
        except Exception:
            pass
        if use_tls and port != 636:
            conn.start_tls_s()
        return conn

    def _as_dict(self, conf):
        if isinstance(conf, dict):
            return conf
        return {
            'ldap_filter': conf.ldap_filter,
            'ldap_base': conf.ldap_base,
            'ldap_binddn': conf.ldap_binddn,
            'ldap_password': conf.ldap_password,
            'ldap_server': conf.ldap_server,
            'ldap_server_port': conf.ldap_server_port,
            'ldap_tls': conf.ldap_tls,
            'create_user': conf.create_user,
            'user': getattr(conf.user, 'id', False),
            'company': (conf.company.id, conf.company.name) if conf.company else False,
        }

    def _get_entry(self, conf, login):
        confd = self._as_dict(conf)
        filter_expr = False
        dn = False
        entry = False
        try:
            filter_expr = filter_format(confd['ldap_filter'], (login,))
        except Exception:
            _logger.warning("Could not format LDAP filter. Your filter should contain one '%%s'.")

        if filter_expr:
            results = self._query(confd, tools.ustr(filter_expr))
            results = [i for i in results if i[0]]
            for result in results:
                if len(result[1].get('uid', [])) == 1:
                    entry = result
                    dn = result[0]
                    break
            if not entry:
                _logger.warning("No matching LDAP entries found for filter: %s", filter_expr)
        else:
            _logger.warning("No LDAP filter available. Unable to perform query.")
        return dn, entry

    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        changed = False
        message = ""
        confd = self._as_dict(conf)

        dn, entry = self._get_entry(conf, login)
        _logger.info('DN: %s, Entry: %s', dn, entry)

        admindn = confd['ldap_binddn']
        adminpw = confd['ldap_password']

        if not dn:
            _logger.info('User not found in LDAP directory, creating...')
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', login)], limit=1)

            if user:
                full_name = (user.partner_id.name or '').strip()
                parts = full_name.split()
                if len(parts) == 1:
                    first_name = parts[0]; last_name = ''
                elif len(parts) == 2:
                    first_name, last_name = parts
                else:
                    first_name = ' '.join(parts[:-1]); last_name = parts[-1]

                first_name = first_name or 'Default First Name'
                last_name = last_name or 'Default Last Name'

                attrs = {
                    "uid": [login.encode()],
                    "givenname": [first_name.encode()],
                    "cn": [(full_name or login).encode()],
                    "sn": [last_name.encode()],
                    "userPassword": [new_passwd.encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                email = getattr(user.partner_id, 'email', None)
                if email:
                    attrs["mail"] = [email.encode()]

                dn = f'uid={login}, {confd["ldap_base"]}'
                created, message = self._create_ldap_user(conf, dn, attrs)
                if created:
                    return True, message
                return False, message

            return False, "User not found in LDAP directory."

        try:
            conn = self._pyldap_connect(conf)
            conn.simple_bind_s(admindn, adminpw)
            conn.passwd_s(dn, None, new_passwd)
            changed = True
            message = 'Success'
            conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            _logger.error('An LDAP exception occurred: %s', e)
            message = 'An LDAP exception occurred: ' + str(e)
        except ldap.LDAPError as e:
            _logger.error('An LDAP exception occurred: %s', e)
            message = 'An LDAP exception occurred: ' + str(e)
        return changed, message

    def _ldap_attr_text(self, attrs, key, default=""):
        try:
            vals = attrs.get(key) or []
            if not vals:
                return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    def _get_uid_from_attrs(self, attrs):
        try:
            vals = attrs.get('uid') or []
            if not vals:
                return ''
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return ''

    def _ldap_find_by_attrs(self, conf, attrs):
        confd = self._as_dict(conf)

        def _query_filter(flt):
            try:
                return self._query(confd, flt)
            except Exception:
                return []

        mail = self._ldap_attr_text(attrs, 'mail').strip()
        if mail:
            f = filter_format('(&(objectClass=inetOrgPerson)(mail=%s))', (mail,))
            res = [r for r in _query_filter(f) if r and r[0]]
            if res:
                for r in res:
                    if r[0]:
                        return r[0], r

        cn = (self._ldap_attr_text(attrs, 'cn') or '').strip()
        if cn:
            f = filter_format('(&(objectClass=inetOrgPerson)(cn=%s))', (cn,))
            res = [r for r in _query_filter(f) if r and r[0]]
            if res:
                return res[0][0], res[0]

        given = (self._ldap_attr_text(attrs, 'givenname') or '').strip()
        sn = (self._ldap_attr_text(attrs, 'sn') or '').strip()
        if given and sn:
            f = filter_format('(&(objectClass=inetOrgPerson)(givenName=%s)(sn=%s))', (given, sn))
            res = [r for r in _query_filter(f) if r and r[0]]
            if res:
                return res[0][0], res[0]

        return False, False

    def _get_or_create_user(self, conf, login, ldap_entry):
        env = self.env
        confd = self._as_dict(conf)
        existing_user = False

        login_norm = tools.ustr(login or "").lower().strip()

        env.cr.execute("SELECT id, active FROM res_users WHERE lower(login)=%s", (login_norm,))
        row = env.cr.fetchone()
        if row and row[1]:
            existing_user = True
            return row[0], existing_user

        mapped_vals = self._map_ldap_attributes(conf, login_norm, ldap_entry) or {}
        company_id = mapped_vals.get('company_id') or env.company.id

        def _find_partner_for_attrs(a):
            def _txt(key, default=""):
                try:
                    vals = a.get(key) or []
                    if not vals:
                        return default
                    v = vals[0]
                    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
                except Exception:
                    return default
            email = (_txt('mail') or '').strip()
            email_norm = email.lower()
            cn = (_txt('cn') or '').strip()
            given = (_txt('givenname') or '').strip()
            sn = (_txt('sn') or '').strip()

            P = env['res.partner'].with_context(active_test=False).sudo()
            if email:
                partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
                if not partner:
                    try:
                        env.cr.execute("SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1",
                                       (email_norm,))
                        r = env.cr.fetchone()
                        if r:
                            partner = P.browse(r[0])
                    except Exception:
                        pass
                if partner:
                    return partner
            if cn:
                partner = P.search([('name', '=', cn)], limit=1)
                if partner:
                    return partner
            nm = (f"{given} {sn}".strip())
            if nm:
                partner = P.search([('name', '=', nm)], limit=1)
                if partner:
                    return partner
            return False

        def _create_user_for_partner(partner, final_login):
            SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
            vals = dict(mapped_vals)
            vals.update({
                'login': final_login,
                'partner_id': partner.id,
                'active': True,
            })
            if partner.email and not vals.get('email'):
                vals['email'] = partner.email

            template_id = None
            v = confd.get('user')
            if isinstance(v, (list, tuple)) and v:
                template_id = v[0]
            elif isinstance(v, int):
                template_id = v
            if template_id:
                return SudoUser.browse(template_id).copy(default=vals).id
            return SudoUser.create(vals).id

        provided_attrs = (ldap_entry[1] if ldap_entry else {}) or {}
        for dn_found, entry_found in (
            self._ldap_find_by_attrs(confd, provided_attrs),
            self._get_entry(confd, login_norm),
        ):
            if entry_found:
                ldap_attrs = entry_found[1]
                ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or login_norm).lower().strip()

                email = (self._ldap_attr_text(ldap_attrs, 'mail') or '').strip().lower()
                if email:
                    user_by_email = env['res.users'].with_context(active_test=False).sudo().search(
                        ['|', ('email', '=', email), ('login', '=', email)], limit=1
                    )
                    if user_by_email and user_by_email.active:
                        existing_user = True
                        if (user_by_email.login or '').lower() != ldap_uid:
                            user_by_email.sudo().write({'login': ldap_uid})
                        return user_by_email.id, existing_user

                partner = _find_partner_for_attrs(ldap_attrs)
                if not partner:
                    partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
                user_id = _create_user_for_partner(partner, ldap_uid)
                return user_id, existing_user

        dn_provided, attrs_provided = ldap_entry or (None, None)
        if not dn_provided or not isinstance(attrs_provided, dict):
            return _("Missing LDAP attributes for new entry"), existing_user

        created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
        if not created:
            return _("LDAP create failed: %s") % msg, existing_user

        partner = _find_partner_for_attrs(attrs_provided)
        if not partner:
            partner = ensure_partner_from_ldap(env, attrs_provided, company_id)
        user_id = _create_user_for_partner(partner, login_norm)
        return user_id, existing_user

    def _create_ldap_user(self, conf, user_dn, attributes):
        created = False
        message = ""

        confd = self._as_dict(conf)
        admindn = confd['ldap_binddn']
        adminpw = confd['ldap_password']

        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(admindn, adminpw)
            modlist_data = modlist.addModlist(attributes)
            conn.add_s(user_dn, modlist_data)
            created = True
            message = 'Success'
            conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            _logger.error('An LDAP exception occurred: %s', e)
            message = 'An LDAP exception occurred: ' + str(e)
        except ldap.LDAPError as e:
            if e.args and isinstance(e.args[0], dict) and e.args[0].get('desc') == 'Already exists':
                _logger.warning('The LDAP entry already exists: %s', e)
                message = 'The LDAP entry already exists: ' + str(e)
            else:
                _logger.error('An LDAP exception occurred: %s', e)
                message = 'An LDAP exception occurred: ' + str(e)

        return created, message

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        values = super()._map_ldap_attributes(conf, login, ldap_entry) or {}

        company_id = False
        if isinstance(conf, dict):
            company_val = conf.get('company')
            if isinstance(company_val, (list, tuple)) and company_val:
                company_id = company_val[0]
            elif isinstance(company_val, int):
                company_id = company_val
        else:
            try:
                company_id = conf.company.id if getattr(conf, 'company', False) else False
            except Exception:
                company_id = False

        values['company_id'] = company_id or self.env.company.id

        if values.get('login'):
            values['login'] = tools.ustr(values['login']).lower().strip()
        else:
            values['login'] = tools.ustr(login).lower().strip()

        return values
