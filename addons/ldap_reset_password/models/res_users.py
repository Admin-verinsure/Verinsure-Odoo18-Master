from odoo.exceptions import UserError
from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
import logging
from datetime import date

_logger = logging.getLogger(__name__)

class ResUsers(models.Model):
    _inherit = 'res.users'

    @classmethod
    def authenticate(cls, db, login, password, user_agent_env=None):
        res = cls._login(db, login, password)
        uid = res[0] if isinstance(res, tuple) else res
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
        _logger.info("action_reset_password: Start")
        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
        user = self

        _logger.info("action_reset_password: Processing user: %s", user.name)

        if self.filtered(lambda user: not user.active):
            raise UserError(_("You cannot perform this action on an archived user."))
        
        create_mode = bool(self.env.context.get('create_user'))
        subject = "Change password for " + user.name
        if create_mode:
            subject = "Welcome to " + user.company_id.name + " " + user.name
        
        website_domain = http.request.httprequest.headers.get('Host').split(':')[0]
        if website_domain == "localhost":
            website_domain = "rotaryoceania.zone"
        email_from = f"no-reply@{website_domain}"
        
        administrator = env['res.users'].search([], limit=1, order='id')
        administrator_email = administrator.partner_id.email_normalized if administrator.partner_id else ""

        mail_template = env['mail.template'].sudo().search([('name', '=', 'LDAP Invitation Email')], limit=1)
        email_values = {'email_from': email_from}
        custom_context = {
            'subject': subject,
            'administrator_email': administrator_email,
            'email_from': email_from
        }

        for user in self:
            _logger.info("action_reset_password: Processing for user: %s, email: %s", user.login, user.partner_id.email)
            if not user.partner_id.email:
                raise UserError(_("Cannot send email: user %s has no email address.", user.name))
            with self.env.cr.savepoint():
                mail_template.with_context(custom_context).sudo().send_mail(user.id, email_values)
            _logger.info("Password reset email sent for user <%s> to <%s>", user.login, user.partner_id.email)
        
        _logger.info("action_reset_password: End")

    def clear_signup_urls(self):
        users = self.sudo().search([])
        users.sudo().write({'signup_url': ''})
        return True

    @api.model
    def create(self, vals):
        user = super().create(vals)
        user.groups_id = False
        role = self.env['res.users.role'].search([('name', '=', 'Guests')], limit=1)
        start_date = fields.Date.today()
        end_date = fields.Date.to_string(date(2099, 12, 31))

        currentRole = self.env['res.users.role.line'].search([('user_id', '=', user.id)])
        guestRole = self.env['res.users.role.line'].search([('user_id', '=', user.id), ('role_id', '=', role.id)])

        if currentRole or guestRole:
            user.set_groups_from_roles()
            return user
        self.env['res.users.role.line'].create({
            'user_id': user.id,
            'role_id': role.id,
            'date_from': start_date,
            'date_to': end_date,
        })
        user.set_groups_from_roles()
        return user
