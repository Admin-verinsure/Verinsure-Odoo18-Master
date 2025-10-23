# -*- coding: utf-8 -*-
import logging, random, string, threading
from datetime import datetime, timedelta

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo import registry as odoo_registry

_logger = logging.getLogger(__name__)

# --- async mail queue kicker (unchanged) ---
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
                            _logger.warning("PWRESET: mail queue process method not found on this Odoo version")
                    except Exception as e:
                        _logger.warning("PWRESET: async mail queue processing failed: %s", e)
                    cr.commit()
        except Exception as e:
            _logger.warning("PWRESET: async sender thread crashed: %s", e)

    th = threading.Thread(target=_runner, name="otp-mail-sender", daemon=True)
    try:
        th.start()
    except Exception as e:
        _logger.warning("PWRESET: could not start async sender thread: %s", e)


# --- small model extension from old code ---
class ResPartner(models.Model):
    _inherit = 'res.partner'
    rotary_membership_id = fields.Char(string="Rotary ID")


# --- backend change password wizard (unchanged) ---
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


# --- PUBLIC CONTROLLER: OTP flow (unchanged) ---
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
                return request.render('ldap_reset_password.template_otp_entry', values)

            env = api.Environment(request.cr, SUPERUSER_ID, {})
            try:
                otp = env['otp'].search([('otp_code', '=', otp_code)], limit=1)
                if not otp:
                    values['error_message'] = "One Time Password not found!"
                    return request.render('ldap_reset_password.template_otp_entry', values)

                if otp.expiration_time < datetime.now() - timedelta(minutes=15):
                    values['error_message'] = "One Time Password has expired!"
                    return request.render('ldap_reset_password.template_otp_entry', values)

                user = env['res.users'].search([('login', '=', username)], limit=1)
                if not user or otp.user_id.id != user.id:
                    values['error_message'] = "User not found or One Time Password mismatch!"
                    return request.render('ldap_reset_password.template_otp_entry', values)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    values['error_message'] = "No LDAP Configuration. Please contact a System administrator via the helpdesk."
                    return request.render('ldap_reset_password.template_otp_entry', values)

                changed, message = ldap_rec._change_password_admin_exceptions(ldap_rec, username, new_password)
                if not changed:
                    values['error_message'] = "Password reset has failed for: " + username + "."
                    return request.render('ldap_reset_password.template_otp_entry', values)

                user.password = ''
                user.sudo()._set_password()
                return request.render('ldap_reset_password.portal_thanks', {
                    'message': 'Password reset has succeeded for {}'.format(username)
                })
            except Exception as e:
                values['error_message'] = f"An error occurred: {e}"
                return request.render('ldap_reset_password.template_otp_entry', values)

        # Phase 1: request OTP
        if kwargs.get('login'):
            username = kwargs.get('login')
            env = api.Environment(request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', username)], limit=1)

            administrator = env['res.users'].search([], limit=1, order='id')
            administrator_email = administrator.partner_id.email_normalized if administrator.partner_id else ""

            if user:
                if user.partner_id.email:
                    otp_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                    expiration_time = datetime.now() + timedelta(minutes=15)
                    env['otp'].create({'user_id': user.id, 'otp_code': otp_code, 'expiration_time': expiration_time})

                    request.env.cr.commit()

                    website_domain = request.httprequest.headers.get('Host').split(':')[0]
                    subject = "One Time Password for Password Change Verification"
                    if website_domain == "localhost":
                        website_domain = "rotaryoceania.zone"
                    email_from = f"no-reply@{website_domain}"
                    email_to = user.partner_id.email

                    mail_tmpl = env['mail.template'].sudo().search([('name', '=', 'Reset LDAP Password Email')], limit=1)
                    ctx = {
                        'subject': subject,
                        'otp_code': otp_code,
                        'administrator_email': administrator_email,
                        'email_from': email_from,
                    }

                    try:
                        mail_tmpl.with_context(ctx).sudo().send_mail(
                            user.id,
                            force_send=False,
                            raise_exception=False,
                            email_values={'email_from': email_from, 'email_to': email_to},
                        )
                    except Exception as e:
                        _logger.warning("PWRESET: failed to queue OTP email for %s: %s", username, e)

                    request.env.cr.commit()

                    try:
                        _kick_async_mail_send(request.env.cr.dbname)
                    except Exception as e:
                        _logger.warning("PWRESET: could not trigger async mail sender: %s", e)

                    return request.render('ldap_reset_password.template_otp_entry', {'login': username})

                return request.render('ldap_reset_password.template_contact_admin')
            return request.render('ldap_reset_password.template_invalid_login')

        return request.render('ldap_reset_password.template_otp', {'message': 'Placeholder'})

    @http.route('/web/reset_password', type='http', auth="public", website=True)
    def reset_password(self):
        return request.redirect('/web/reset_ldap_password')
