# -*- coding: utf-8 -*-
import ldap
import ldap.modlist as modlist
import logging
import threading
from datetime import datetime, timedelta
from ldap.filter import filter_format

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo import registry as odoo_registry

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async mail queue processor
# ---------------------------------------------------------------------------
def _kick_async_mail_send(db_name: str):
    """Run mail queue processing asynchronously."""
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
                            _logger.warning("No mail queue processor found")
                    except Exception as e:
                        _logger.warning("Async mail processing failed: %s", e)
                    cr.commit()
        except Exception as e:
            _logger.warning("Async sender crashed: %s", e)
    threading.Thread(target=_runner, name="ldap-mail-sender", daemon=True).start()


# ---------------------------------------------------------------------------
# Partner Extension
# ---------------------------------------------------------------------------
class ResPartner(models.Model):
    _inherit = 'res.partner'
    rotary_membership_id = fields.Char(string="Rotary ID")


# ---------------------------------------------------------------------------
# Password Change Wizard
# ---------------------------------------------------------------------------
class ChangePasswordWizard(models.TransientModel):
    _name = 'change.password.wizard'
    _inherit = 'change.password.wizard'

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

    wizard_id = fields.Many2one('change.password.wizard', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    user_login = fields.Char(string='User Login', readonly=True)
    new_passwd = fields.Char(string='New Password', default='')

    def change_password_button(self):
        user = self.user_id
        if not self.new_passwd:
            raise UserError(_("Before clicking 'Change Password', please write a new password."))

        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
        ldap_conf = env['res.company.ldap'].search([], limit=1)
        if not ldap_conf:
            raise UserError(_("No LDAP configuration found."))

        changed, message = ldap_conf._change_password_admin_exceptions(ldap_conf, user.login, self.new_passwd)
        if not changed:
            raise UserError(message or _("Password change failed."))
        user.password = ''
        user._set_password()
        return {'type': 'ir.actions.act_window_close'}


# ---------------------------------------------------------------------------
# LDAP Reset Controller  (FIXED)
# ---------------------------------------------------------------------------
class LDAPResetController(http.Controller):

    @http.route('/web/Morris_reset_ldap_password', type='http', auth='public', website=True, csrf=False)
    def reset_ldap_password(self, **kwargs):
        """Two-phase LDAP password reset process using OTP."""
        env = api.Environment(http.request.cr, SUPERUSER_ID, {})

        # Phase 2 — verify OTP + change password
        if kwargs.get('otp') and kwargs.get('login'):
            login = kwargs.get('login')
            otp_code = kwargs.get('otp')
            new_pwd = kwargs.get('new_password')
            confirm = kwargs.get('confirm_password')

            if new_pwd != confirm:
                return request.render('Morris_ldap_reset_password.template_otp_entry', {
                    'login': login,
                    'password_error': "Passwords do not match!"
                })

            otp = env['otp'].sudo().search([('otp_code', '=', otp_code)], limit=1)
            if not otp:
                return request.render('Morris_ldap_reset_password.template_otp_entry', {
                    'error_message': "OTP not found."
                })

            now_utc = fields.Datetime.now()
            if getattr(otp, 'expiration_time', False):
                if now_utc > otp.expiration_time:
                    return request.render('Morris_ldap_reset_password.template_otp_entry', {
                        'error_message': "OTP expired. Please re-generate the OTP."
                    })
            else:
                if otp.create_date and now_utc > (otp.create_date + timedelta(minutes=10)):
                    return request.render('Morris_ldap_reset_password.template_otp_entry', {
                        'error_message': "OTP expired. Please re-generate the OTP."
                    })

            user = env['res.users'].sudo().search([('login', '=', login)], limit=1)
            if not user or otp.user_id.id != user.id:
                return request.render('Morris_ldap_reset_password.template_otp_entry', {
                    'error_message': "Invalid user or OTP."
                })

            ldap_conf = env['res.company.ldap'].search([], limit=1)
            if not ldap_conf:
                return request.render('Morris_ldap_reset_password.template_otp_entry', {
                    'error_message': "LDAP configuration missing."
                })

            changed, message = ldap_conf._change_password_admin_exceptions(ldap_conf, login, new_pwd)
            if not changed:
                return request.render('Morris_ldap_reset_password.template_otp_entry', {
                    'error_message': f"Password reset failed: {message}"
                })

            user.password = ''
            user.sudo()._set_password()

            return request.render('Morris_ldap_reset_password.template_otp', {
                'message': f"Password reset successful for {login}."
            })

        # Phase 1 — request OTP
        if kwargs.get('login'):
            login = kwargs.get('login')
            user = env['res.users'].sudo().search([('login', '=', login)], limit=1)
            if user and user.partner_id.email:
                try:
                    user.sudo().action_reset_password()
                    _kick_async_mail_send(env.cr.dbname)
                    return request.render('Morris_ldap_reset_password.template_otp_entry', {
                        'login': login
                    })
                except Exception as e:
                    _logger.error("Error sending OTP: %s", e)
                    return request.render('Morris_ldap_reset_password.template_otp', {
                        'message': "Error sending OTP — please contact admin."
                    })

            return request.render('Morris_ldap_reset_password.template_otp', {
                'message': "Username not found."
            })

        # Default initial page
        return request.render('Morris_ldap_reset_password.template_otp', {
            'message': 'Enter your username to reset password.'
        })

    @http.route('/web/reset_password', type='http', auth='public', website=True)
    def reset_password_redirect(self):
        """Redirect old route to new one."""
        return request.redirect('/web/Morris_reset_ldap_password')


# ---------------------------------------------------------------------------
# LDAP Model Extension
# ---------------------------------------------------------------------------
class CompanyLDAP(models.Model):
    _inherit = 'res.company.ldap'

    def _pyldap_connect(self, conf):
        host = getattr(conf, 'ldap_server', None) or conf.get('ldap_server')
        port = int(getattr(conf, 'ldap_server_port', None) or conf.get('ldap_server_port', 389))
        use_tls = bool(getattr(conf, 'ldap_tls', None) or conf.get('ldap_tls', False))
        uri = f"{'ldaps' if port == 636 else 'ldap'}://{host}:{port}"

        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
        conn.set_option(ldap.OPT_TIMEOUT, 5)
        conn.set_option(ldap.OPT_REFERRALS, 0)
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
        }


    def _get_entry(self, conf, login):
        confd = self._as_dict(conf)
        try:
            fexpr = filter_format(confd['ldap_filter'], (login,))
            results = self._query(confd, tools.ustr(fexpr))
            for dn, attrs in results:
                if dn and len(attrs.get('uid', [])) == 1:
                    return dn, (dn, attrs)
        except Exception as e:
            _logger.warning("LDAP entry lookup failed: %s", e)
        return None, None

    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        """Change LDAP password or create user if missing."""
        confd = self._as_dict(conf)
        dn, entry = self._get_entry(conf, login)
        admindn = confd['ldap_binddn']
        adminpw = confd['ldap_password']

        if not dn:
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].sudo().search([('login', '=', login)], limit=1)
            if user:
                full_name = user.partner_id.name or login
                parts = full_name.split()
                first = parts[0] if parts else 'Default'
                last = parts[-1] if len(parts) > 1 else first
                attrs = {
                    "uid": [login.encode()],
                    "cn": [full_name.encode()],
                    "givenname": [first.encode()],
                    "sn": [last.encode()],
                    "userPassword": [new_passwd.encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }
                if user.partner_id.email:
                    attrs["mail"] = [user.partner_id.email.encode()]
                dn = f"uid={login},{confd['ldap_base']}"
                return self._create_ldap_user(confd, dn, attrs)
            return False, "User not found in LDAP."

        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(admindn, adminpw)
            conn.passwd_s(dn, None, new_passwd)
            conn.unbind_s()
            return True, "Success"
        except ldap.LDAPError as e:
            return False, f"LDAP Error: {e}"

    def _create_ldap_user(self, conf, dn, attrs):
        try:
            confd = self._as_dict(conf)
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(confd['ldap_binddn'], confd['ldap_password'])
            conn.add_s(dn, modlist.addModlist(attrs))
            conn.unbind_s()
            return True, "User created successfully."
        except ldap.ALREADY_EXISTS:
            return True, "Already exists."
        except ldap.LDAPError as e:
            return False, str(e)
