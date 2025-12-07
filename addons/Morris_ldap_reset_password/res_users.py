from odoo.exceptions import UserError
from odoo import api, fields, models, SUPERUSER_ID, _, http

import logging
from datetime import date, datetime, timedelta
import random

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    # keep your authenticate as-is
    @classmethod
    def authenticate(cls, db, login, password, user_agent_env=None):
        res = cls._login(db, login, password)
        if isinstance(res, tuple):
            uid, _ = res
        else:
            uid = res

        if user_agent_env and user_agent_env.get('base_location'):
            with cls.pool.cursor() as cr:
                env = api.Environment(cr, uid, {})
                if env.user.has_group('base.group_system'):
                    try:
                        base = user_agent_env['base_location']
                        ICP = env['ir.config_parameter']
                        if not ICP.get_param('web.base.url.freeze'):
                            ICP.set_param('web.base.url', base)
                    except Exception:
                        _logger.exception("Failed to update web.base.url configuration parameter")
        return uid

    def action_reset_password(self):
        """
        Send OTP mail without using mail.template, and without linking to any model,
        so Odoo cannot try to re-render {{...}} from a template.
        """
        _logger.info("action_reset_password: Start")

        # superuser env (we're in http)
        env = api.Environment(http.request.cr, SUPERUSER_ID, {})

        # block archived users (your original logic)
        if self.filtered(lambda u: not u.active):
            raise UserError(_("You cannot perform this action on an archived user."))

        # figure out from-domain
        website_domain = http.request.httprequest.headers.get('Host').split(':')[0]
        if website_domain == "localhost":
            website_domain = "rotaryoceania.zone"
        email_from = f"no-reply@{website_domain}"

        # admin email - optional footer
        administrator = env['res.users'].search([], limit=1, order='id')
        administrator_email = administrator.partner_id.email_normalized if administrator.partner_id else ""

        for user in self:
            if not user.partner_id.email:
                raise UserError(_("Cannot send email: user %s has no email address.", user.name))

            # subject like before
            create_mode = bool(self.env.context.get('create_user'))
            if create_mode:
                subject = "Welcome to %s %s" % (user.company_id.name, user.name)
            else:
                subject = "One Time Password for Password Change Verification"

            # 1) generate and store OTP
            otp_code = str(random.randint(100000, 999999))
            expires_at = datetime.utcnow() + timedelta(minutes=10)

            env['otp'].sudo().create({
                'user_id': user.id,
                'otp_code': otp_code,
                'expiration_time': fields.Datetime.to_string(expires_at),
            })

            # 2) build pure HTML
            body_html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
                <p>Hello {user.name or ''},</p>
                <p>We received a request to reset the password for your account.</p>
                <p>Your One-Time Password (OTP) is:</p>
                <p style="font-size: 22px; font-weight: bold; letter-spacing: 2px; margin: 15px 0;">
                    {otp_code}
                </p>
                <p>This OTP will expire in <strong>10</strong> minutes.</p>
                <p>If you did not request this password reset, you can ignore this email.</p>
                <hr style="margin: 20px 0; border: 0; border-top: 1px solid #ddd;"/>
                <p style="font-size: 12px; color: #777;">
                    Sent by {email_from}.
            """

            if administrator_email:
                body_html += f"You may also contact {administrator_email}."
            body_html += "</p></div>"

            # 3) create a PLAIN mail.mail (no model/res_id) so Odoo won’t try to re-render
            mail_vals = {
                'subject': subject,
                'body_html': body_html,
                'email_from': email_from,
                'email_to': user.partner_id.email,
                'auto_delete': False,
                # critical: do NOT link to any record/template
                'model': False,
                'res_id': False,
                'message_id': False,
            }
            mail = env['mail.mail'].sudo().create(mail_vals)

            # send now
            mail.sudo().send()

            _logger.info(
                "Password reset OTP mail sent for user <%s> to <%s> with OTP %s",
                user.login, user.partner_id.email, otp_code
            )

        _logger.info("action_reset_password: End")

    def clear_signup_urls(self):
        users = self.sudo().search([])
        users.sudo().write({'signup_url': ''})
        return True

    @api.model
    def create(self, vals):
        # unchanged user create
        user = super(ResUsers, self).create(vals)

        # Clear the groups
        user.groups_id = False

        # Search for the role with the name "Guests"
        role = self.env['res.users.role'].search([('name', '=', 'Guests')], limit=1)

        # Set the start and end dates for the role
        start_date = fields.Date.today()
        end_date = fields.Date.to_string(date(2099, 12, 31))

        currentRole = self.env['res.users.role.line'].search([
            ('user_id', '=', user.id),
        ])
        guestRole = self.env['res.users.role.line'].search([
            ('user_id', '=', user.id),
            ('role_id', '=', role.id),
        ])

        if currentRole:
            user.set_groups_from_roles()
            return user
        elif guestRole:
            user.set_groups_from_roles()
            return user
        else:
            self.env['res.users.role.line'].create({
                'user_id': user.id,
                'role_id': role.id,
                'date_from': start_date,
                'date_to': end_date,
            })
            user.set_groups_from_roles()
            return user