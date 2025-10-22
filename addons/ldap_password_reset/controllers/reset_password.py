# -*- coding: utf-8 -*-
import logging, random, string, threading
from datetime import datetime, timedelta

from odoo import http, api, SUPERUSER_ID
from odoo.http import request
from odoo import registry as odoo_registry

_logger = logging.getLogger(__name__)

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
    t = threading.Thread(target=_runner, name="otp-mail-sender", daemon=True)
    try:
        t.start()
    except Exception as e:
        _logger.warning("PWRESET: could not start async sender thread: %s", e)

class LDAPResetController(http.Controller):

    @http.route('/web/reset_password', type='http', auth="public", website=True)
    def reset_password_shortcut(self):
        # keep legacy link working
        return request.redirect('/web/reset_ldap_password')

    @http.route('/web/reset_ldap_password', type='http', auth='public', website=True, csrf=False)
    def reset_ldap_password(self, **kwargs):
        # Phase 2: OTP + new password
        if kwargs.get('otp') and kwargs.get('login') and kwargs.get('new_password') and kwargs.get('confirm_password'):
            otp_code = kwargs['otp']
            username = kwargs['login']
            new_password = kwargs['new_password']
            confirm_password = kwargs['confirm_password']

            values = {'login': username}
            if new_password != confirm_password:
                values['password_error'] = "Passwords do not match!"
                return request.render('ldap_password_reset.template_otp_entry', values)

            env = api.Environment(request.cr, SUPERUSER_ID, {})
            try:
                otp = env['otp'].search([('otp_code', '=', otp_code)], limit=1)
                if not otp:
                    values['error_message'] = "One Time Password not found!"
                    return request.render('ldap_password_reset.template_otp_entry', values)

                if otp.expiration_time < datetime.now() - timedelta(minutes=15):
                    values['error_message'] = "One Time Password has expired!"
                    return request.render('ldap_password_reset.template_otp_entry', values)

                user = env['res.users'].search([('login', '=', username)], limit=1)
                if not user or otp.user_id.id != user.id:
                    values['error_message'] = "User not found or One Time Password mismatch!"
                    return request.render('ldap_password_reset.template_otp_entry', values)

                ldap_rec = env['res.company.ldap'].search([], limit=1)
                if not ldap_rec:
                    values['error_message'] = "No LDAP Configuration. Please contact a System administrator via the helpdesk."
                    return request.render('ldap_password_reset.template_otp_entry', values)

                changed, message = ldap_rec._change_password_admin_exceptions(ldap_rec, username, new_password)
                if not changed:
                    _logger.warning("PWRESET: LDAP password change failed for %s: %s", username, message)
                    values['error_message'] = "Password reset has failed for: " + username + "."
                    return request.render('ldap_password_reset.template_otp_entry', values)

                user.password = ''
                user.sudo()._set_password()
                return request.render('ldap_password_reset.portal_thanks', {
                    'message': 'Password reset has succeeded for {}'.format(username)
                })
            except Exception as e:
                _logger.exception("PWRESET: phase2 error")
                values['error_message'] = "An unexpected error occurred. Please try again."
                return request.render('ldap_password_reset.template_otp_entry', values)

        # Phase 1: request OTP
        if kwargs.get('login'):
            username = kwargs['login']
            env = api.Environment(request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', username)], limit=1)

            if user:
                if user.partner_id.email:
                    otp_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                    expiration_time = datetime.now() + timedelta(minutes=15)
                    env['otp'].create({'user_id': user.id, 'otp_code': otp_code, 'expiration_time': expiration_time})

                    # commit OTP row immediately
                    request.env.cr.commit()

                    website_domain = request.httprequest.headers.get('Host').split(':')[0]
                    if website_domain == "localhost":
                        website_domain = "rotaryoceania.zone"
                    subject = "One Time Password for Password Change Verification"
                    email_from = f"no-reply@{website_domain}"
                    email_to = user.partner_id.email

                    mail_tmpl = env['mail.template'].sudo().search(
                        [('name', '=', 'Reset LDAP Password Email')], limit=1
                    )
                    ctx = {'subject': subject, 'otp_code': otp_code, 'email_from': email_from}

                    try:
                        mail_tmpl.with_context(ctx).sudo().send_mail(
                            user.id,
                            force_send=False,  # queue fast
                            raise_exception=False,
                            email_values={'email_from': email_from, 'email_to': email_to},
                        )
                    except Exception as e:
                        _logger.warning("PWRESET: failed to queue OTP email for %s: %s", username, e)

                    request.env.cr.commit()
                    # trigger background send (non-blocking, no UI delay)
                    _kick_async_mail_send(request.env.cr.dbname)

                    # immediately show OTP entry screen (never blocks)
                    return request.render('ldap_password_reset.template_otp_entry', {'login': username})
                return request.render('ldap_password_reset.template_contact_admin')
            return request.render('ldap_password_reset.template_invalid_login')

        return request.render('ldap_password_reset.template_otp', {'message': 'Placeholder'})
