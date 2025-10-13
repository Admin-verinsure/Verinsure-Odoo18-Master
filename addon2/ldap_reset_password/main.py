# -*- coding: utf-8 -*-

# Replaced python-ldap with ldap3 throughout.
# - add_s / passwd_s => ldap3 Connection.add / Connection.modify or Microsoft extension
# - simple_bind_s    => Connection(..., auto_bind=True) or conn.rebind(...)
# - ldap.filter      => ldap3.utils.conv.escape_filter_chars

from ldap3 import Server, Connection, ALL, Tls, MODIFY_REPLACE
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars
import ssl

import logging
import werkzeug
import random
import string
import json

from datetime import datetime, timedelta, date
from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.tools.misc import str2bool
from odoo.tools.pycompat import to_text
from odoo.http import content_disposition, Controller, request, route
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController
from odoo.addons.mail.models.mail_mail import MailMail
from odoo.addons.mail.models.mail_template import MailTemplate

_logger = logging.getLogger(__name__)

SIGN_UP_REQUEST_PARAMS = {'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
                          'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
                          'password', 'confirm_password', 'city', 'country_id', 'lang',
                          'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id'
}

# -----------------------------
# LDAP helper utilities (ldap3)
# -----------------------------

def _conf_get(conf, key, default=None):
    """Conf may be a browse record or a dict (from .read())."""
    if isinstance(conf, dict):
        return conf.get(key, default)
    return getattr(conf, key, default)

def _ldap3_connect(conf, bind_dn, bind_pw):
    host = _conf_get(conf, 'ldap_server', '127.0.0.1')
    port = int(_conf_get(conf, 'ldap_server_port', 389))
    use_tls_flag = bool(_conf_get(conf, 'ldap_tls', False))

    # ldaps if 636; otherwise StartTLS if ldap_tls is enabled
    use_ssl = (port == 636)
    tls = Tls(validate=ssl.CERT_NONE)  # tighten to CERT_REQUIRED + CA if you have CA file
    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL, tls=tls)

    conn = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True)
    if use_tls_flag and not use_ssl:
        conn.start_tls()
    return conn

def _to_ldap3_attrs(d):
    """Convert python-ldap style {attr: [bytes,...]} to ldap3 {attr: [str,...]}."""
    out = {}
    for k, v in (d or {}).items():
        vals = v if isinstance(v, (list, tuple)) else [v]
        out[k] = [vv.decode() if isinstance(vv, (bytes, bytearray)) else str(vv) for vv in vals]
    return out

def _format_filter(ldap_filter_tmpl, login):
    """Emulate ldap.filter.filter_format(…) using ldap3's escaping."""
    try:
        return ldap_filter_tmpl % (escape_filter_chars(tools.ustr(login)),)
    except Exception:
        _logger.warning("Could not format LDAP filter. Your filter should contain one '%%s'.")
        return None

# -----------------------------


class ResPartner(models.Model):
    _inherit = 'res.partner'
    rotary_membership_id = fields.Char(string="Rotary ID")


class ChangePasswordWizard(models.TransientModel):
    """ A wizard to manage the change of users' passwords. """
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

        if len(new_passwd) == 0:
            raise UserError(_("Before clicking on 'Change Password', you have to write a new password."))

        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
        ldap_records = env['res.company.ldap'].search([])
        ldap_dict = {}
        for record in ldap_records:
            ldap_dict[record.id] = record.read()

        if ldap_dict:
            first_ldap_id = next(iter(ldap_dict))
            ldap_config = env['res.company.ldap'].browse(first_ldap_id)
        else:
            ldap_config = None

        if ldap_config:
            changed, message = ldap_config._change_password_admin_exceptions(ldap_config, username, new_passwd)

            if changed:
                _logger.info("Password reset has succeeded for: %s.", username)
                user_id.password = ''
                user_id._set_password()
                return {'type': 'ir.actions.act_window_close'}
            else:
                _logger.error("Password reset has failed for: %s.", username)
                raise UserError(message)
        else:
            _logger.info("No LDAP Config.")
            raise UserError('No LDAP Configuration found.')


class LDAPResetController(http.Controller):

    @http.route('/web/reset_ldap_password', type='http', auth='public', website=True)
    def reset_ldap_password(self, **kwargs):

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
                        return http.request.render('ldap_reset_password.portal_thanks',
                                                   {'message': 'Password reset has succeeded for {}'.format(username)})
                    else:
                        _logger.info("LDAP Server produced the following error: %s", message)
                        error_response_values['error_message'] = "Password reset has failed for: " + username + "."
                        return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)
                else:
                    error_response_values['error_message'] = "No LDAP Configuration. Please contact a System administrator via the helpdesk."
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

            except Exception as e:
                error_response_values['error_message'] = f"An error occurred: {e}"
                return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

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

                    website_domain = http.request.httprequest.headers.get('Host')
                    subject = "One Time Password for Password Change Verification"

                    website_domain = website_domain.split(':')[0]
                    if website_domain == "localhost":
                        website_domain = "rotaryoceania.zone"
                    email_from = f"no-reply@{website_domain}"

                    mail_template = env['mail.template'].sudo().search([('name', '=', 'Reset LDAP Password Email')], limit=1)
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

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ldap_records = env['res.company.ldap'].search([])
                ldap_dict = {}
                for record in ldap_records:
                    ldap_dict[record.id] = record.read()

                if ldap_dict:
                    first_ldap_id = next(iter(ldap_dict))
                    ldap_config = env['res.company.ldap'].browse(first_ldap_id)
                else:
                    ldap_config = None

                if ldap_config:
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = str(generate_random_number(5, 8))
                    login = sn + rotaryId
                    cn = fn + ' ' + sn
                    dn = "uid=" + login + ", " + ldap_config.ldap_base

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
                    user_id, existing_user = ldap_config._get_or_create_user(ldap_config, login, ldap_entry, True)

                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error', {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
                        _logger.info('res_user created. Creating LDAP User for: %s', login)
                        created, message = ldap_config._create_ldap_user(ldap_config, dn, attrs)

                        if created:
                            user = request.env['res.users'].sudo().browse(user_id)
                            role = env['res.users.role'].search([('name', '=', 'Guests')])

                            if rotaryId.isdigit():
                                user.partner_id.write({'rotary_membership_id': str(rotaryId)})
                            else:
                                _logger.info("User %s: provided rotaryId cannot be converted to an integer.", user.login)

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

                            return http.request.render('ldap_reset_password.web_thanks', {'message': 'You have created user: {}'.format(login)})
                        else:
                            delete_user = self.env['res.users'].browse(user_id)
                            delete_user.unlink()
                            return http.request.render('ldap_reset_password.web_error', {'message': message + '.'})

                    elif isinstance(user_id, str):
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))

            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        response = request.render('ldap_reset_password.signup_non_member', qcontext)
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()

        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        clubs = []
        for partner in partners_club_name_not_empty:
            if partner.club_name is not None and partner.club_name != '':
                clubs.append(partner)

        qcontext['clubs'] = clubs

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ldap_records = env['res.company.ldap'].search([])
                ldap_dict = {}
                for record in ldap_records:
                    ldap_dict[record.id] = record.read()

                if ldap_dict:
                    first_ldap_id = next(iter(ldap_dict))
                    ldap_config = env['res.company.ldap'].browse(first_ldap_id)
                else:
                    ldap_config = None

                if ldap_config:
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = qcontext['rotary_id']
                    login = sn + rotaryId
                    cn = fn + ' ' + sn
                    dn = "uid=" + login + ", " + ldap_config.ldap_base

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
                    user_id, existing_user = ldap_config._get_or_create_user(ldap_config, login, ldap_entry, True)

                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error', {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
                        _logger.info('res_user created. Creating LDAP User for: %s', login)
                        created, message = ldap_config._create_ldap_user(ldap_config, dn, attrs)

                        if created:
                            user = request.env['res.users'].sudo().browse(user_id)

                            if rotaryId.isdigit():
                                user.partner_id.write({
                                    'rotary_club_id': rotary_club_id,
                                    'rotary_membership_id': str(rotaryId)
                                })
                            else:
                                user.partner_id.write({'rotary_club_id': rotary_club_id})
                                _logger.info("User %s: provided rotaryId cannot be converted to an integer.", user.login)

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

                            return http.request.render('ldap_reset_password.web_thanks', {'message': 'You have created user: {}'.format(login)})
                        else:
                            delete_user = self.env['res.users'].browse(user_id)
                            delete_user.unlink()
                            return http.request.render('ldap_reset_password.web_error', {'message': message + '.'})

                    elif isinstance(user_id, str):
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))

            except Exception as e:
                _logger.error("%s", e)
                qcontext['error'] = _("Could not create account. " + str(e))

        response = request.render('ldap_reset_password.signup', qcontext)
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    def get_auth_signup_qcontext(self):
        """ Shared helper returning the rendering context for signup and reset password """
        qcontext = {k: v for (k, v) in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
        qcontext.update(self.get_auth_signup_config())
        if not qcontext.get('token') and request.session.get('auth_signup_token'):
            qcontext['token'] = request.session.get('auth_signup_token')
        if qcontext.get('token'):
            try:
                token_infos = request.env['res.partner'].sudo().signup_retrieve_info(qcontext.get('token'))
                for k, v in token_infos.items():
                    qcontext.setdefault(k, v)
            except:
                qcontext['error'] = _("Invalid signup token")
                qcontext['invalid_token'] = True
        return qcontext


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
    ldap_binddn = fields.Char('LDAP binddn',
        help="The user account on the LDAP server that is used to query the directory. "
             "Leave empty to connect anonymously.")
    ldap_password = fields.Char(string='LDAP password',
        help="The password of the user account on the LDAP server that is used to query the directory.")
    ldap_filter = fields.Char(string='LDAP filter', required=True)
    ldap_base = fields.Char(string='LDAP base', required=True)
    user = fields.Many2one('res.users', string='Template User',
        help="User to copy when creating new users")
    create_user = fields.Boolean(default=True,
        help="Automatically create local user accounts for new users authenticating via LDAP")
    ldap_tls = fields.Boolean(string='Use TLS',
        help="Request secure TLS/SSL encryption when connecting to the LDAP server. "
             "This option requires a server with STARTTLS enabled, "
             "otherwise all authentication attempts will fail.")

    # -----------------------------
    # LDAP queries / changes
    # -----------------------------

    def _get_entry(self, conf, login):
        dn, entry = False, False
        flt = _format_filter(_conf_get(conf, 'ldap_filter', ''), login)
        if flt:
            results = self._query(conf, tools.ustr(flt))
            results = [i for i in results if i[0]]  # drop search references
            for result in results:
                if len(result[1].get('uid', [])) == 1:
                    entry = result
                    dn = result[0]
                    break
            if entry:
                _logger.info("Found matching LDAP entry: %s", entry)
            else:
                _logger.warning("No matching LDAP entries found for filter: %s", flt)
        else:
            _logger.warning("No LDAP filter available. Unable to perform query.")
        return dn, entry

    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        """Admin-driven password change. If user not found, create entry first."""
        changed, message = False, ""

        dn, entry = self._get_entry(conf, login)
        _logger.info('DN: %s, Entry: %s', dn, entry)

        admindn = _conf_get(conf, 'ldap_binddn')
        adminpw = _conf_get(conf, 'ldap_password')

        if not dn:
            _logger.info('User not found in LDAP directory, creating...')
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', login)], limit=1)

            if user:
                full_name = user.partner_id.name.strip()
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
                    "cn": [full_name.encode()],
                    "sn": [last_name.encode()],
                    "userPassword": [new_passwd.encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                email = getattr(user.partner_id, 'email', None)
                if email:
                    attrs["mail"] = [email.encode()]

                ou = getattr(user.partner_id, 'rotary_club_id', None)
                if ou and getattr(ou, 'club_id', False):
                    attrs["ou"] = [ou.club_id.encode()]

                rotary_id = extract_rotary_id(login, last_name)
                if rotary_id:
                    attrs["employeeNumber"] = [rotary_id.encode()]

                dn = 'UID=' + login + ', ' + self.ldap_base
                created, message = self._create_ldap_user(conf, dn, attrs)
                return (True, message) if created else (False, message)

        # change password on existing DN
        try:
            conn = _ldap3_connect(conf, admindn, adminpw)

            # Try Microsoft AD extended op first; if that fails, do OpenLDAP-style replace
            ok = False
            try:
                # AD supports old_password=None for admin reset
                ok = conn.extend.microsoft.modify_password(dn, new_passwd)
            except Exception:
                ok = False

            if not ok:
                ok = conn.modify(dn, {'userPassword': [(MODIFY_REPLACE, [new_passwd])]})

            if ok:
                changed, message = True, 'Success'
            else:
                _logger.error('LDAP password change failed: %s', conn.result)
                message = f"LDAP password change failed: {conn.result}"
            conn.unbind()
        except LDAPBindError as e:
            _logger.error('LDAP bind failed: %s', e)
            message = f'LDAP bind failed: {e}'
        except LDAPException as e:
            _logger.error('LDAP exception: %s', e)
            message = f'LDAP exception: {e}'
        return changed, message

    # Optional: user-driven change (old->new) used by portal security page
    def _change_password_exceptions(self, conf, login, old_passwd, new_passwd):
        """User-driven password change: bind as the user first; fall back to admin."""
        changed, message = False, ""
        dn, entry = self._get_entry(conf, login)
        if not dn:
            return False, "User not found in LDAP directory."

        # Try self-bind then modify
        try:
            conn = _ldap3_connect(conf, dn, old_passwd)  # bind as the user
            ok = False
            try:
                ok = conn.extend.microsoft.modify_password(dn, new_passwd, old_password=old_passwd)
            except Exception:
                ok = False
            if not ok:
                ok = conn.modify(dn, {'userPassword': [(MODIFY_REPLACE, [new_passwd])]})
            if ok:
                changed, message = True, "Success"
            else:
                message = f"LDAP password change failed: {conn.result}"
            conn.unbind()
            if changed:
                return changed, message
        except LDAPException as e:
            # fall through to admin attempt
            _logger.warning("Self-bind password change failed: %s; attempting admin-assisted change.", e)

        # Admin-assisted change
        return self._change_password_admin_exceptions(conf, login, new_passwd)

    def _get_or_create_user(self, conf, login, ldap_entry, with_existing=False):
        existing_user = False
        login = tools.ustr(login.lower().strip())
        self.env.cr.execute("SELECT id, active FROM res_users WHERE lower(login)=%s", (login,))
        res = self.env.cr.fetchone()
        _logger.debug("Fetched user: %s", res)

        if res and res[1]:
            existing_user = True
            return (res[0], existing_user) if with_existing else res[0]

        Users = self.env['res.users'].sudo()
        Partners = self.env['res.partner'].sudo()

        mapped = self._map_ldap_attributes(conf, login, ldap_entry) or {}

        login_str = (mapped.get('login') or login)
        email = (mapped.get('email') or mapped.get('mail'))
        name = (mapped.get('name') or (email or login_str) or 'LDAP User')

        if email:
            user_by_email = Users.search([('email', '=', email)], limit=1)
            if user_by_email:
                existing_user = True
                return (user_by_email.id, existing_user) if with_existing else user_by_email.id

        create_user_flag = conf.get('create_user') if isinstance(conf, dict) else getattr(conf, 'create_user', False)
        if not create_user_flag:
            raise AccessDenied(_("No local user found for LDAP login and not configured to create one"))

        partner = False
        P = Partners.with_context(active_test=False)
        if email:
            norm = (email or '').strip().lower()
            try:
                partner = P.search(['|', ('email', '=', email), ('email_normalized', '=', norm)], limit=1)
            except Exception:
                partner = P.search([('email', '=', email)], limit=1)

        if not partner and name:
            cands = P.search([('name', '=', name)], order='create_date asc', limit=5)
            if cands:
                if email:
                    pmatch = cands.filtered(lambda r: (r.email or '').strip().lower() == (email or '').strip().lower())
                    partner = (pmatch[:1] or cands[:1])
                else:
                    partner = cands[:1]

        if not partner:
            try:
                partner = Partners.create({'name': name, 'email': email})
            except Exception as e:
                _logger.warning("Partner create failed (%s); retrying by reusing existing partner", e)
                partner = P.search(['|', ('email', '=', email), ('name', '=', name)], order='id asc', limit=1)
                if not partner:
                    raise
        elif not partner.active:
            partner.write({'active': True})

        u2 = Users.search([('partner_id', '=', partner.id)], limit=1)
        if u2:
            upd = {}
            if login_str and u2.login != login_str:
                upd['login'] = login_str
            if email and u2.email != email:
                upd['email'] = email
            if upd:
                u2.write(upd)
            existing_user = True
            return (u2.id, existing_user) if with_existing else u2.id

        values = {'partner_id': partner.id, 'login': login_str}

        portal_gid = False
        for xmlid in ('portal.group_portal', 'base.group_portal'):
            try:
                portal_gid = self.env.ref(xmlid).id
                break
            except Exception:
                pass
        if portal_gid:
            values['groups_id'] = [(6, 0, [portal_gid])]

        SudoUser = Users.with_context(no_reset_password=True)

        if isinstance(conf, dict):
            val = conf.get('user')
            template_id = val[0] if isinstance(val, (list, tuple)) else val
        else:
            template_id = getattr(getattr(conf, 'user', None), 'id', False)

        if template_id:
            values['active'] = True
            user_id = SudoUser.browse(template_id).copy(default=values).id
            _logger.debug("Created new user from template: %s", user_id)
            return (user_id, existing_user) if with_existing else user_id

        user_id = SudoUser.create(values).id
        _logger.debug("Created new user: %s", user_id)
        return (user_id, existing_user) if with_existing else user_id

    def _create_ldap_user(self, conf, user_dn, attributes):
        created = False
        message = ""

        admindn = _conf_get(conf, 'ldap_binddn')
        adminpw = _conf_get(conf, 'ldap_password')

        try:
            conn = _ldap3_connect(conf, admindn, adminpw)
            attrs = _to_ldap3_attrs(attributes)
            ok = conn.add(user_dn, attributes=attrs)
            if ok:
                created, message = True, 'Success'
            else:
                desc = (conn.result or {}).get('description', 'unknown')
                if desc in ('entryAlreadyExists', 'alreadyExists'):
                    _logger.warning('The LDAP entry already exists: %s', conn.result)
                    message = 'The LDAP entry already exists'
                else:
                    _logger.error('LDAP add failed: %s', conn.result)
                    message = f"LDAP add failed: {conn.result}"
            conn.unbind()
        except LDAPBindError as e:
            _logger.error('LDAP bind failed: %s', e)
            message = f'LDAP bind failed: {e}'
        except LDAPException as e:
            _logger.error('LDAP exception: %s', e)
            message = f'LDAP exception: {e}'

        return created, message

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        values = super()._map_ldap_attributes(conf, login, ldap_entry) or {}

        company_id = False
        if isinstance(conf, dict):
            company = conf.get('company')
            if isinstance(company, (list, tuple)) and company:
                company_id = company[0]
            elif isinstance(company, int):
                company_id = company
        else:
            try:
                company_id = conf.company.id if getattr(conf, 'company', False) else False
            except Exception:
                company_id = False

        values.setdefault('company_id', company_id or self.env.company.id)
        return values


class CustomerPortal(Controller):

    MANDATORY_BILLING_FIELDS = ["name", "phone", "email", "street", "city", "country_id"]
    OPTIONAL_BILLING_FIELDS = ["zipcode", "state_id", "vat", "company_name"]

    _items_per_page = 20

    def _prepare_portal_layout_values(self):
        sales_user = False
        partner = request.env.user.partner_id
        if partner.user_id and not partner.user_id._is_public():
            sales_user = partner.user_id

        return {
            'sales_user': sales_user,
            'page_name': 'home',
        }

    @route('/my/security', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def security(self, **post):
        env = request.env
        values = self._prepare_portal_layout_values()
        values['get_error'] = get_error
        result = ''

        if request.httprequest.method == 'POST':
            username = env.user.login
            result = self._update_password(
                post['old'].strip(),
                post['new1'].strip(),
                post['new2'].strip(),
                username)

        if len(result) > 0:
            success = result.get('success')
            if success is not None and len(success) > 0:
                new_token = request.env.user._compute_session_token(request.session.sid)
                request.session.session_token = new_token
                return http.request.render('ldap_reset_password.portal_thanks',
                                           {'message': 'Password reset has succeeded for {}'.format(username)})

            state = result.get('error', {}).get('state')
            if state == 'invalid':
                return http.request.render('ldap_reset_password.portal_error', {'message': 'Invalid old password.'})
            elif state == 'refused':
                return http.request.render('ldap_reset_password.portal_error', {'message': 'Password change refused by LDAP server.'})
            elif state == 'misc':
                message = result.get('error', {}).get('message')
                return http.request.render('ldap_reset_password.portal_error', {'message': 'Uncommon Error: ' + message + '.'})
            elif state == 'unknown':
                message = result.get('error', {}).get('message')
                return http.request.render('ldap_reset_password.portal_error', {'message': 'Unknown Error: ' + message + '.'})

        return request.render('portal.portal_my_security', values, headers={'X-Frame-Options': 'DENY'})

    def _update_password(self, old, new1, new2, username):
        for k, v in [('old', old), ('new1', new1), ('new2', new2)]:
            if not v:
                return {'errors': {'password': {k: _("You cannot leave any password empty.")}}}

        if new1 != new2:
            return {'errors': {'password': {'new2': _("The new password and its confirmation must be identical.")}}}

        old_passwd = old
        new_passwd = new1

        _logger.info("Calling LDAPAPI. Updating LDAP Password for %s!", username)

        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
        ldap_records = env['res.company.ldap'].search([])
        ldap_dict = {}
        for record in ldap_records:
            ldap_dict[record.id] = record.read()

        if ldap_dict:
            first_ldap_id = next(iter(ldap_dict))
            ldap_config = env['res.company.ldap'].browse(first_ldap_id)
        else:
            ldap_config = None

        if ldap_config:
            changed, message = ldap_config._change_password_exceptions(ldap_config, username, old_passwd, new_passwd)

            if changed:
                _logger.info("Password reset has succeeded for: %s.", username)
                user = env['res.users'].search([('login', '=', username)])
                if user:
                    user.password = ''
                    user._set_password()
                    user.invalidate_cache(['password'], [user.id])
                return {'success': {'state': 'changed'}}

            elif not changed and "INVALID_CREDENTIALS" in tools.ustr(message):
                _logger.error("Password reset has failed for: %s. Invalid old password.", username)
                return {'error': {'state': 'invalid'}}

            elif not changed and "UNWILLING_TO_PERFORM" in tools.ustr(message):
                _logger.error("Password reset has failed for: %s. Password change refused by LDAP server.", username)
                return {'error': {'state': 'refused'}}

            elif not changed and "Success" not in tools.ustr(message):
                _logger.error("Password reset has failed for: %s. LDAP error: %s", username, message)
                return {'error': {'state': 'misc', 'message': str(message)}}

            else:
                _logger.error("Password reset has failed for: %s. Unhandled Error: %s", username, message)
                return {'error': {'state': 'unknown', 'message': str(message)}}

        return {'error': {'state': 'unknown', 'message': 'No LDAP configuration'}}


def extract_rotary_id(login, last_name):
    login = login.lower()
    last_name = last_name.lower()
    potential_id = login.replace(last_name, '')
    if 5 <= len(potential_id) <= 8:
        return potential_id
    else:
        return None

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
