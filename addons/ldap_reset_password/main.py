# -*- coding: utf-8 -*-

# Low-level python-ldap for raw LDAP operations (bind, add, passwd, etc.)
import ldap
import ldap.modlist as modlist

# Odoo & stdlib
import logging
import werkzeug
import random
import string

from datetime import datetime, timedelta, date
from ldap.filter import filter_format
from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import Controller, request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController

_logger = logging.getLogger(__name__)

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
        return [(0, 0, {'user_id': u.id, 'user_login': u.login}) for u in self.env['res.users'].browse(user_ids)]

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
        user = self.user_id
        username = str(user.login)
        new_passwd = self.new_passwd

        if not new_passwd:
            raise UserError(_("Before clicking on 'Change Password', you have to write a new password."))

        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
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

    @http.route('/web/reset_ldap_password', type='http', auth='public', website=True, csrf=False)
    def reset_ldap_password(self, **kwargs):
        # Phase 2: OTP + new password
        if kwargs.get('otp') and kwargs.get('login') and kwargs.get('new_password') and kwargs.get('confirm_password'):
            otp_code = kwargs.get('otp')
            username = kwargs.get('login')
            new_password = kwargs.get('new_password')
            confirm_password = kwargs.get('confirm_password')

            values = {'login': username}
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
                    values['error_message'] = "No LDAP Configuration. Please contact a System administrator via the helpdesk."
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
                    env['otp'].create({'user_id': user.id, 'otp_code': otp_code, 'expiration_time': expiration_time})

                    website_domain = http.request.httprequest.headers.get('Host').split(':')[0]
                    subject = "One Time Password for Password Change Verification"
                    if website_domain == "localhost":
                        website_domain = "rotaryoceania.zone"
                    email_from = f"no-reply@{website_domain}"

                    mail_tmpl = env['mail.template'].sudo().search([('name', '=', 'Reset LDAP Password Email')], limit=1)
                    email_values = {'email_from': email_from}
                    ctx = {'subject': subject, 'otp_code': otp_code, 'administrator_email': administrator_email, 'email_from': email_from}
                    mail_tmpl.with_context(ctx).sudo().send_mail(user.id, email_values)
                    return http.request.render('ldap_reset_password.template_otp_entry', {'login': username})
                return http.request.render('ldap_reset_password.template_contact_admin')
            return http.request.render('ldap_reset_password.template_invalid_login')

        return http.request.render('ldap_reset_password.template_otp', {'message': 'Placeholder'})

    @http.route('/web/reset_password', type='http', auth="public", website=True)
    def reset_password(self):
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
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_reset_password.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if ldap_rec:
                    sn = qcontext['last_name']; fn = qcontext['first_name']
                    rotaryId = str(generate_random_number(5, 8))
                    mail = qcontext
                    login = sn + rotaryId
                    cn = f"{fn} {sn}"
                    dn = f"uid={login}, {ldap_rec.ldap_base}"

                    attrs = {
                        "uid": [login.encode()], "givenname": [fn.encode()], "cn": [cn.encode()], "sn": [sn.encode()],
                        "employeeNumber": [rotaryId.encode()], "mail": [qcontext['email'].encode()],
                        "userPassword": [qcontext['password'].encode()], "objectclass": [b"top", b"inetOrgPerson"],
                    }

                    user_id, existing_user = ldap_rec._get_or_create_user(ldap_rec, login, (dn, attrs))
                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error', {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
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
                                'user_id': user.id, 'role_id': role.id,
                                'date_from': date.today(), 'date_to': date(2099, 12, 31)
                            })
                            user.set_groups_from_roles()

                        return http.request.render('ldap_reset_password.web_thanks', {'message': f'You have created user: {user.login}'})
                    else:
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))
            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        resp = request.render('ldap_reset_password.signup_non_member', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

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
                    sn = qcontext['last_name']; fn = qcontext['first_name']
                    rotaryId = qcontext['rotary_id']; login = sn + rotaryId
                    cn = f"{fn} {sn}"; dn = f"uid={login}, {ldap_rec.ldap_base}"
                    rotary_club_id = int(qcontext['rotary_club_id'])

                    attrs = {
                        "uid": [login.encode()], "givenname": [fn.encode()], "cn": [cn.encode()], "sn": [sn.encode()],
                        "ou": [str(rotary_club_id).encode()], "employeeNumber": [qcontext['rotary_id'].encode()],
                        "mail": [qcontext['email'].encode()], "userPassword": [qcontext['password'].encode()],
                        "objectclass": [b"top", b"inetOrgPerson"],
                    }

                    user_id, existing_user = ldap_rec._get_or_create_user(ldap_rec, login, (dn, attrs))
                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error', {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
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
                                'user_id': user.id, 'role_id': role.id,
                                'date_from': date.today(), 'date_to': date(2099, 12, 31)
                            })
                            user.set_groups_from_roles()

                        return http.request.render('ldap_reset_password.web_thanks', {'message': f'You have created user: {user.login}'})
                    else:
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))
            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

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
# Utilities
# ---------------------------------------------------------------------------

def extract_rotary_id(login, last_name):
    login = (login or '').lower()
    last_name = (last_name or '').lower()
    potential_id = login.replace(last_name, '')
    return potential_id if potential_id.isdigit() and 5 <= len(potential_id) <= 8 else None

def generate_random_number(min_length, max_length):
    return random.randint(10 ** (min_length - 1), (10 ** max_length) - 1)

# Only block on an existing *user* e-mail, not a *contact*.
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

# ---------- partner helper (module-level) ----------
def ensure_partner_from_ldap(env, attrs, company_id):
    """
    Idempotent partner lookup/create by LDAP attrs.
    If a unique-email constraint/validation fires, reuse the existing partner.
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


# ---------------------------------------------------------------------------
# LDAP model (override)
# ---------------------------------------------------------------------------

class CompanyLDAP(models.Model):
    _inherit = 'res.company.ldap'

    # ---------- raw python-ldap connection ----------
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
        dn = entry = False
        try:
            fexpr = filter_format(confd['ldap_filter'], (login,))
        except Exception:
            _logger.warning("Could not format LDAP filter. Your filter should contain one '%%s'.")
            fexpr = False
        if fexpr:
            results = self._query(confd, tools.ustr(fexpr))
            results = [r for r in results if r[0]]
            for r in results:
                if len(r[1].get('uid', [])) == 1:
                    entry = r
                    dn = r[0]
                    break
        return dn, entry

    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        changed = False
        message = ""
        confd = self._as_dict(conf)

        dn, entry = self._get_entry(conf, login)
        admindn = confd['ldap_binddn']; adminpw = confd['ldap_password']

        if not dn:
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', login)], limit=1)
            if user:
                full_name = (user.partner_id.name or '').strip() or login
                parts = full_name.split()
                first_name = parts[0] if parts else 'Default First Name'
                last_name = parts[-1] if len(parts) > 1 else 'Default Last Name'
                attrs = {
                    "uid": [login.encode()], "givenname": [first_name.encode()],
                    "cn": [full_name.encode()], "sn": [last_name.encode()],
                    "userPassword": [new_passwd.encode()], "objectclass": [b"top", b"inetOrgPerson"],
                }
                email = getattr(user.partner_id, 'email', None)
                if email:
                    attrs["mail"] = [email.encode()]
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
        def _q(flt):
            try: return self._query(confd, flt)
            except Exception: return []
        mail = (self._ldap_attr_text(attrs, 'mail') or '').strip()
        if mail:
            res = [r for r in _q(filter_format('(&(objectClass=inetOrgPerson)(mail=%s))', (mail,))) if r and r[0]]
            if res: return res[0][0], res[0]
        cn = (self._ldap_attr_text(attrs, 'cn') or '').strip()
        if cn:
            res = [r for r in _q(filter_format('(&(objectClass=inetOrgPerson)(cn=%s))', (cn,))) if r and r[0]]
            if res: return res[0][0], res[0]
        given = (self._ldap_attr_text(attrs, 'givenname') or '').strip()
        sn = (self._ldap_attr_text(attrs, 'sn') or '').strip()
        if given and sn:
            res = [r for r in _q(filter_format('(&(objectClass=inetOrgPerson)(givenName=%s)(sn=%s))', (given, sn))) if r and r[0]]
            if res: return res[0][0], res[0]
        return False, False

    def _get_or_create_user(self, conf, login, ldap_entry):
        """
        Robust path:
        - If in LDAP but not an Odoo user → find/reuse contact → create user & attach.
        - If not in LDAP → create LDAP → create/find contact → create user.
        """
        env = self.env
        confd = self._as_dict(conf)
        existing_user = False
        login_norm = tools.ustr(login or "").lower().strip()

        env.cr.execute("SELECT id, active FROM res_users WHERE lower(login)=%s", (login_norm,))
        row = env.cr.fetchone()
        if row and row[1]:
            return row[0], True

        mapped_vals = self._map_ldap_attributes(conf, login_norm, ldap_entry) or {}
        company_id = mapped_vals.get('company_id') or env.company.id

        def _find_partner_for_attrs(a):
            def _t(key, default=""):
                try:
                    vals = a.get(key) or []
                    v = vals[0] if vals else default
                    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
                except Exception:
                    return default
            email = (_t('mail') or '').strip()
            email_norm = email.lower()
            cn = (_t('cn') or '').strip()
            given = (_t('givenname') or '').strip()
            sn = (_t('sn') or '').strip()

            P = env['res.partner'].with_context(active_test=False).sudo()
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
                if partner: return partner
            if cn:
                partner = P.search([('name', '=', cn)], limit=1)
                if partner: return partner
            nm = (f"{given} {sn}".strip())
            if nm:
                partner = P.search([('name', '=', nm)], limit=1)
                if partner: return partner
            return False

        def _create_user_for_partner(partner, final_login):
            """Create a user attached to an existing partner, without touching partner email."""
            SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
            vals = dict(mapped_vals)
            vals.update({'login': final_login, 'partner_id': partner.id, 'active': True})
            # Do NOT pass 'email' so create() won't attempt to write partner.email (avoids uniqueness clash).
            if 'email' in vals:
                vals.pop('email', None)
            return SudoUser.create(vals).id

        attrs_given = (ldap_entry[1] if ldap_entry else {}) or {}

        # 1) LDAP by email/name then by uid (reuse uid)
        for dn_found, entry_found in (self._ldap_find_by_attrs(confd, attrs_given), self._get_entry(confd, login_norm)):
            if entry_found:
                ldap_attrs = entry_found[1]
                ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or login_norm).lower().strip()
                email = (self._ldap_attr_text(ldap_attrs, 'mail') or '').strip().lower()

                if email:
                    U = env['res.users'].with_context(active_test=False).sudo()
                    user_by_email = U.search(['|', ('email', '=', email), ('login', '=', email)], limit=1)
                    if user_by_email and user_by_email.active:
                        existing_user = True
                        if (user_by_email.login or '').lower() != ldap_uid:
                            user_by_email.sudo().write({'login': ldap_uid})
                        return user_by_email.id, existing_user

                partner = _find_partner_for_attrs(ldap_attrs) or ensure_partner_from_ldap(env, ldap_attrs, company_id)
                user_id = _create_user_for_partner(partner, ldap_uid)
                return user_id, existing_user

        # 2) Not in LDAP → create LDAP → partner → user
        dn_provided, attrs_provided = ldap_entry or (None, None)
        if not dn_provided or not isinstance(attrs_provided, dict):
            return _("Missing LDAP attributes for new entry"), existing_user

        created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
        if not created:
            return _("LDAP create failed: %s") % msg, existing_user

        partner = _find_partner_for_attrs(attrs_provided) or ensure_partner_from_ldap(env, attrs_provided, company_id)
        user_id = _create_user_for_partner(partner, login_norm)
        return user_id, existing_user

    def _create_ldap_user(self, conf, user_dn, attributes):
        created = False
        message = ""
        confd = self._as_dict(conf)
        admindn = confd['ldap_binddn']; adminpw = confd['ldap_password']
        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(admindn, adminpw)
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
        values = super()._map_ldap_attributes(conf, login, ldap_entry) or {}
        company_id = False
        if isinstance(conf, dict):
            v = conf.get('company')
            if isinstance(v, (list, tuple)) and v:
                company_id = v[0]
            elif isinstance(v, int):
                company_id = v
        else:
            try:
                company_id = conf.company.id if getattr(conf, 'company', False) else False
            except Exception:
                company_id = False
        values['company_id'] = company_id or self.env.company.id
        values['login'] = tools.ustr(values.get('login') or login).lower().strip()
        return values
