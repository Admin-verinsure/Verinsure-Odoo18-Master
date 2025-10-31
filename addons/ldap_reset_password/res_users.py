from odoo.exceptions import UserError
from odoo import api, fields, models, tools, SUPERUSER_ID, _, http

import logging
from datetime import date, datetime, timedelta
import random

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    # ---- keep your custom authenticate exactly as is ----
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
        Your original method sent a template directly, so variables stayed unrendered.
        Here we:
        1. generate OTP
        2. store OTP in your `otp` model
        3. render the mail template FIRST
        4. create mail.mail and send
        and we keep the 'create_user' behavior.
        """
        _logger.info("action_reset_password: Start")

        # superuser env because we are inside http request
        env = api.Environment(http.request.cr, SUPERUSER_ID, {})

        if self.filtered(lambda u: not u.active):
            raise UserError(_("You cannot perform this action on an archived user."))

        # figure out subject
        create_mode = bool(self.env.context.get('create_user'))
        # self at this point can be multi, but we will compute per-user below
        website_domain = http.request.httprequest.headers.get('Host').split(':')[0]
        if website_domain == "localhost":
            website_domain = "rotaryoceania.zone"
        email_from = f"no-reply@{website_domain}"

        # admin email for footer
        administrator = env['res.users'].search([], limit=1, order='id')
        administrator_email = administrator.partner_id.email_normalized if administrator.partner_id else ""

        # try to get our dedicated reset template FIRST
        # (this is the one you defined in reset_ldap_password.xml)
        reset_tmpl = env.ref('ldap_reset_password.reset_ldap_password', raise_if_not_found=False)
        # fallback to your old template name
        if not reset_tmpl:
            reset_tmpl = env['mail.template'].sudo().search(
                [('name', '=', 'LDAP Invitation Email')], limit=1
            )

        for user in self:
            _logger.info("action_reset_password: Processing user: %s, email: %s", user.login, user.partner_id.email)

            if not user.partner_id.email:
                raise UserError(_("Cannot send email: user %s has no email address.", user.name))

            # subject may change per user
            subject = "Change password for " + user.name
            if create_mode:
                subject = "Welcome to %s %s" % (user.company_id.name, user.name)

            # -----------------------------
            # 1) create OTP and store it
            # -----------------------------
            otp_code = str(random.randint(100000, 999999))
            expires_at = datetime.utcnow() + timedelta(minutes=10)

            env['otp'].sudo().create({
                'user_id': user.id,
                'otp_code': otp_code,
                'expiration_time': fields.Datetime.to_string(expires_at),
            })

            # -----------------------------
            # 2) context for template render
            # -----------------------------
            tctx = {
                'subject': subject,
                'administrator_email': administrator_email,
                'email_from': email_from,
                'otp_code': otp_code,
                'otp_expiration_minutes': 10,
            }

            # -----------------------------
            # 3) render template
            # -----------------------------
            if reset_tmpl:
                # render body
                rendered_body = reset_tmpl.with_context(tctx).sudo()._render_template(
                    reset_tmpl.body_html,
                    reset_tmpl.model,
                    user.id,
                ).get(user.id, '')

                # render subject too (otherwise you see {{ ... }} in subject)
                rendered_subject = reset_tmpl.with_context(tctx).sudo()._render_template(
                    reset_tmpl.subject,
                    reset_tmpl.model,
                    user.id,
                ).get(user.id, subject)
            else:
                # fallback plain body
                rendered_subject = subject
                rendered_body = (
                    f"<p>Hello {user.name},</p>"
                    f"<p>Your OTP is: <strong>{otp_code}</strong></p>"
                    f"<p>This OTP will expire in 10 minutes.</p>"
                )

            # -----------------------------
            # 4) create mail.mail so you can see it in Technical > Emails
            # -----------------------------
            mail_vals = {
                'subject': rendered_subject,
                'body_html': rendered_body,
                'email_from': email_from,
                'email_to': user.partner_id.email,
                'auto_delete': False,  # keep for debugging
            }

            mail = env['mail.mail'].sudo().create(mail_vals)
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
        # Create the user using the existing logic
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

        # If User has been allocated a role already
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
