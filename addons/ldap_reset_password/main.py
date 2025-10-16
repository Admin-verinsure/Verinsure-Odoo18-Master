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
    # Store Rotary membership id on the partner for reporting/lookup
    rotary_membership_id = fields.Char(string="Rotary ID")


class ChangePasswordWizard(models.TransientModel):
    """Extend the standard wizard so it also updates the LDAP directory."""
    _name = 'change.password.wizard'
    _inherit = 'change.password.wizard'
    _description = "Change Password Wizard"

    def _default_user_ids(self):
        # Build default one2many lines for selected users
        user_ids = self._context.get('active_model') == 'res.users' and self._context.get('active_ids') or []
        return [
            (0, 0, {'user_id': user.id, 'user_login': user.login})
            for user in self.env['res.users'].browse(user_ids)
        ]

    user_ids = fields.One2many('change.password.user', 'wizard_id', string='Users', default=_default_user_ids)

    def change_password_button(self):
        # Apply the operation and keep the current user logged in
        self.ensure_one()
        self.user_ids.change_password_button()
        if self.env.user in self.user_ids.user_id:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return {'type': 'ir.actions.act_window_close'}


class ChangePasswordUser(models.TransientModel):
    """One2many line for the password change wizard."""
    _name = 'change.password.user'
    _inherit = 'change.password.user'
    _description = "User, Change Password LDAP"

    wizard_id = fields.Many2one('change.password.wizard', string='Wizard', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    user_login = fields.Char(string='User Login', readonly=True)
    new_passwd = fields.Char(string='New Password', default='')

    def change_password_button(self):
        # Perform the LDAP admin-side password change, then blank Odoo local password
        user_id = self.user_id
        username = str(user_id.login)
        new_passwd = self.new_passwd

        _logger.info("Calling LDAPAPI. Updating LDAP Password for %s", username)

        if not new_passwd:
            raise UserError(_("Before clicking on 'Change Password', you have to write a new password."))

        # Load LDAP config (first record wins)
        env = api.Environment(http.request.cr, SUPERUSER_ID, {})
        ldap_records = env['res.company.ldap'].search([])
        ldap_dict = {}
        for record in ldap_records:
            ldap_dict[record.id] = record.read()
        ldap_config = env['res.company.ldap'].browse(next(iter(ldap_dict))) if ldap_dict else None

        if ldap_config:
            changed, message = ldap_config._change_password_admin_exceptions(ldap_config, username, new_passwd)
            if changed:
                # Clear local Odoo password so LDAP remains the source of truth
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
        """
        Two-phase flow:
        - Phase 1: POST login → generate OTP and email it.
        - Phase 2: POST login+otp+new_password → verify OTP and set LDAP password.
        """
        # Phase 2: OTP submit with new passwords
        if kwargs.get('otp') and kwargs.get('login') and kwargs.get('new_password') and kwargs.get('confirm_password'):
            otp_code = kwargs.get('otp')
            username = kwargs.get('login')
            new_password = kwargs.get('new_password')
            confirm_password = kwargs.get('confirm_password')

            error_response_values = {'login': username}

            # Client-side safety check
            if new_password != confirm_password:
                error_response_values['password_error'] = "Passwords do not match!"
                return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            try:
                # Look up OTP and validate window
                otp = env['otp'].search([('otp_code', '=', otp_code)], limit=1)
                if not otp:
                    error_response_values['error_message'] = "One Time Password not found!"
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

                if otp.expiration_time < datetime.now() - timedelta(minutes=15):
                    error_response_values['error_message'] = "One Time Password has expired!"
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

                # Ensure OTP belongs to requesting user
                user = env['res.users'].search([('login', '=', username)], limit=1)
                if not user or otp.user_id.id != user.id:
                    error_response_values['error_message'] = "User not found or One Time Password mismatch!"
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

                # Use the first LDAP config
                ldap_config = env['res.company.ldap'].search([], limit=1)

                if ldap_config:
                    # Admin-side reset to avoid requiring the old password
                    changed, message = ldap_config._change_password_admin_exceptions(ldap_config, username, new_password)
                    if changed:
                        _logger.info("Password reset has succeeded for: %s.", username)
                        # Blank Odoo local password
                        user.password = ''
                        user.sudo()._set_password()
                        return http.request.render('ldap_reset_password.portal_thanks', {
                            'message': 'Password reset has succeeded for {}'.format(username)
                        })
                    # LDAP error path
                    _logger.info("LDAP Server produced the following error: %s", message)
                    error_response_values['error_message'] = "Password reset has failed for: " + username + "."
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)
                else:
                    # No LDAP configured (infrastructure issue)
                    error_response_values['error_message'] = (
                        "No LDAP Configuration. Please contact a System administrator via the helpdesk."
                    )
                    return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

            except Exception as e:
                # Generic error catcher to not expose internals to the end user
                error_response_values['error_message'] = f"An error occurred: {e}"
                return http.request.render('ldap_reset_password.template_otp_entry', error_response_values)

        # Phase 1: username submit → generate OTP and send email
        if kwargs.get('login'):
            username = kwargs.get('login')
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', username)])

            # Use first created user as admin email contact fallback
            administrator = env['res.users'].search([], limit=1, order='id')
            administrator_email = administrator.partner_id.email_normalized if administrator.partner_id else ""

            if user:
                if user.partner_id.email:
                    # Generate OTP and persist ~15 minutes
                    otp_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                    expiration_time = datetime.now() + timedelta(minutes=15)
                    env['otp'].create({
                        'user_id': user.id,
                        'otp_code': otp_code,
                        'expiration_time': expiration_time,
                    })

                    # Compose sender addr using Host header (prod-safe)
                    website_domain = http.request.httprequest.headers.get('Host').split(':')[0]
                    subject = "One Time Password for Password Change Verification"
                    if website_domain == "localhost":
                        website_domain = "rotaryoceania.zone"
                    email_from = f"no-reply@{website_domain}"

                    # Use a preconfigured mail template
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

                    # Send the mail and show OTP page
                    mail_template.with_context(custom_context).sudo().send_mail(user.id, email_values)
                    return http.request.render('ldap_reset_password.template_otp_entry', {'login': username})
                else:
                    # No email → route to helpdesk page
                    return http.request.render('ldap_reset_password.template_contact_admin')
            else:
                # Unknown login
                return http.request.render('ldap_reset_password.template_invalid_login')

        # Initial page
        return http.request.render('ldap_reset_password.template_otp', {'message': 'Placeholder'})

    @http.route('/web/reset_password', type='http', auth="public", website=True)
    def reset_password(self):
        # Keep the canonical endpoint but forward to LDAP screen
        _logger.info("Redirecting to Reset LDAP Password.")
        return request.redirect('/web/reset_ldap_password')


class LDAPSignupController(AuthSignupController):
    """Public signup for members & non-members with LDAP provisioning."""

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        # Simple branching page
        return http.request.render('ldap_reset_password.signup_is_member')

    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        # Same controller flow as member signup, but without club assignment
        qcontext = self.get_auth_signup_qcontext()

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                # ---------- fail-fast validation (email → first name → last name)
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(
                    env,
                    qcontext.get('email'),
                    qcontext.get('first_name'),
                    qcontext.get('last_name'),
                )
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_reset_password.signup_non_member', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp
                # ---------- END validation

                ldap_records = env['res.company.ldap'].search([])
                ldap_dict = {rec.id: rec.read() for rec in ldap_records}
                ldap_config = env['res.company.ldap'].browse(next(iter(ldap_dict))) if ldap_dict else None

                if ldap_config:
                    # Build login and LDAP DN
                    sn = qcontext['last_name']
                    fn = qcontext['first_name']
                    rotaryId = str(generate_random_number(5, 8))
                    login = sn + rotaryId
                    cn = f"{fn} {sn}"
                    dn = f"uid={login}, {ldap_config.ldap_base}"

                    # Attributes to create inetOrgPerson
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

                    # Create or reuse Odoo user (this will reuse LDAP uid if user already in LDAP)
                    ldap_entry = (dn, attrs)
                    user_id, existing_user = ldap_config._get_or_create_user(ldap_config, login, ldap_entry)
                    if existing_user:
                        return http.request.render('ldap_reset_password.web_error',
                                                   {'message': 'Error: User already exists.'})

                    if isinstance(user_id, int):
                        _logger.info('res_user created. Ensuring LDAP entry for: %s', login)

                        # Check LDAP by email/name first; create only if missing
                        dn_exist, entry_exist = ldap_config._ldap_find_by_attrs(ldap_config, attrs)
                        if not entry_exist:
                            created, message = ldap_config._create_ldap_user(ldap_config, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return http.request.render('ldap_reset_password.web_error',
                                                           {'message': (message or '') + '.'})

                        # Assign "Guests" role and note Rotary ID
                        user = request.env['res.users'].sudo().browse(user_id)
                        role = env['res.users.role'].search([('name', '=', 'Guests')])

                        if rotaryId.isdigit():
                            user.partner_id.write({'rotary_membership_id': str(rotaryId)})
                        else:
                            _logger.info("User %s: provided rotaryId cannot be converted to an integer.", user.login)

                        # Reset any existing role lines and add a long-lived assignment
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
        # Member flow with club selection
        qcontext = self.get_auth_signup_qcontext()

        # Pull partners having a club_name to populate the dropdown
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        clubs = [p for p in partners_club_name_not_empty if p.club_name]
        qcontext['clubs'] = clubs

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                # ---------- fail-fast validation (email → first name → last name)
                env = api.Environment(http.request.cr, SUPERUSER_ID, {})
                ok, msg = validate_signup_fields(
                    env,
                    qcontext.get('email'),
                    qcontext.get('first_name'),
                    qcontext.get('last_name'),
                )
                if not ok:
                    qcontext['error'] = msg
                    resp = request.render('ldap_reset_password.signup', qcontext)
                    resp.headers['X-Frame-Options'] = 'DENY'
                    return resp
                # ---------- END validation

                ldap_records = env['res.company.ldap'].search([])
                ldap_dict = {rec.id: rec.read() for rec in ldap_records}
                ldap_config = env['res.company.ldap'].browse(next(iter(ldap_dict))) if ldap_dict else None

                if ldap_config:
                    # Build login/DN and club id
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
                        _logger.info('res_user created. Ensuring LDAP entry for: %s', login)

                        # Check LDAP by email/name first; create only if missing
                        dn_exist, entry_exist = ldap_config._ldap_find_by_attrs(ldap_config, attrs)
                        if not entry_exist:
                            created, message = ldap_config._create_ldap_user(ldap_config, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return http.request.render('ldap_reset_password.web_error',
                                                           {'message': (message or '') + '.'})

                        # Assign member role & club, store Rotary ID
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
        # Helper from auth_signup; we extend but keep the same behavior
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
    """From a login like 'smith12345' and last_name 'smith', extract '12345'."""
    login = (login or '').lower()
    last_name = (last_name or '').lower()
    potential_id = login.replace(last_name, '')
    return potential_id if potential_id.isdigit() and 5 <= len(potential_id) <= 8 else None


def get_error(e, path=''):
    """Dot-path helper to pull strings from nested dicts safely."""
    for k in (path.split('.') if path else []):
        if not isinstance(e, dict):
            return None
        e = e.get(k)
    return e if isinstance(e, str) else None


def generate_random_number(min_length, max_length):
    """Random number with digit length in [min_length, max_length]."""
    min_value = 10 ** (min_length - 1)
    max_value = (10 ** max_length) - 1
    return random.randint(min_value, max_value)

# ---------- partner helper (module-level, NOT a model method) ----------
def ensure_partner_from_ldap(env, attrs, company_id):
    """Find or create a partner using LDAP attributes. Priority: email → exact CN."""
    def _attr_text(a, key, default=""):
        try:
            vals = a.get(key) or []
            if not vals:
                return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    email = (_attr_text(attrs, 'mail') or "").strip().lower()
    cn = _attr_text(attrs, 'cn') or ""
    given = _attr_text(attrs, 'givenname')
    sn = _attr_text(attrs, 'sn')
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()

    partner = False
    if email:
        partner = P.search(['|', ('email_normalized', '=', email), ('email', '=', email)], limit=1)
    if not partner and name:
        partner = P.search([('name', '=', name)], limit=1)

    if partner:
        updates = {}
        if email and (partner.email or "").strip().lower() != email:
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
    return P.create(vals)
# ---------- END helper ----------

# ---------- validation helpers ----------
def _email_is_valid(email):
    """Basic single-email validation (uses Odoo regex when available)."""
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
    Step 1: email format + uniqueness (hard stop on failure)
    Step 2: first name present (hard stop on failure)
    Step 3: last name present (hard stop on failure)
    Returns (ok, message). ok=False means stop and show message.
    """
    # Step 1: email checks
    if not email:
        return False, _("Email is required.")
    if not _email_is_valid(email):
        return False, _("Please enter a valid email address.")

    norm = _normalize_email(email)

    # Uniqueness: check partners (active + archived) and users
    P = env['res.partner'].with_context(active_test=False)
    U = env['res.users'].with_context(active_test=False)

    # Prefer normalized email on partner if available, fall back to raw email
    partner_hit = P.search(['|', ('email_normalized', '=', norm), ('email', '=', email)], limit=1)
    if partner_hit:
        return False, _("This email address is already in use.")

    user_hit = U.search([('email', 'ilike', email)], limit=1)
    if user_hit:
        return False, _("This email address is already in use.")

    # Step 2: first name
    if not (first_name or "").strip():
        return False, _("First name is required.")

    # Step 3: last name
    if not (last_name or "").strip():
        return False, _("Last name is required.")

    return True, ""
# ---------- END validation ----------


# ---------------------------------------------------------------------------
# LDAP model (override)
# ---------------------------------------------------------------------------

class CompanyLDAP(models.Model):
    """
    Extend res.company.ldap to:
      - use python-ldap for add_s/passwd_s
      - normalize config (record vs dict)
      - ensure company_id is assigned
      - implement LDAP-first creation policy (LDAP → Partner → User)
      - implement “unique email” user reuse and LDAP uid reuse
    """
    _name = 'res.company.ldap'
    _description = 'Company LDAP configuration'
    _inherit = 'res.company.ldap'
    _order = 'sequence'
    _rec_name = 'ldap_server'

    # Standard config fields
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

    # ---------- raw python-ldap connection (not Odoo LDAP wrapper) ----------
    def _pyldap_connect(self, conf):
        """Return a raw python-ldap connection (not Odoo's LDAPWrapper)."""
        # conf may be a browse record or a dict
        host = getattr(conf, "ldap_server", None) or (conf.get("ldap_server") if isinstance(conf, dict) else "127.0.0.1")
        port = int(getattr(conf, "ldap_server_port", None) or (conf.get("ldap_server_port") if isinstance(conf, dict) else 389))
        use_tls = bool(getattr(conf, "ldap_tls", None) if not isinstance(conf, dict) else conf.get("ldap_tls", False))

        scheme = "ldaps" if port == 636 else "ldap"
        uri = f"{scheme}://{host}:{port}"
        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        try:
            conn.set_option(ldap.OPT_REFERRALS, 0)  # disable referral chasing (esp. AD)
        except Exception:
            pass
        if use_tls and port != 636:
            conn.start_tls_s()
        return conn

    def _as_dict(self, conf):
        """Access fields uniformly whether conf is a record or a dict."""
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
        """Query LDAP and return (dn, entry) for a unique uid match."""
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
            results = [i for i in results if i[0]]  # strip search references
            for result in results:
                if len(result[1].get('uid', [])) == 1:
                    entry = result
                    dn = result[0]
                    break
            if entry:
                _logger.info("Found matching LDAP entry: %s", entry)
            else:
                _logger.warning("No matching LDAP entries found for filter: %s", filter_expr)
        else:
            _logger.warning("No LDAP filter available. Unable to perform query.")
        return dn, entry

    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        """
        Admin reset:
        - If DN exists → set new password with passwd_s
        - If DN missing → create a minimal inetOrgPerson, then return success
        """
        changed = False
        message = ""
        confd = self._as_dict(conf)

        dn, entry = self._get_entry(conf, login)
        _logger.info('DN: %s, Entry: %s', dn, entry)

        admindn = confd['ldap_binddn']
        adminpw = confd['ldap_password']

        # If no LDAP entry, create it from the Odoo user profile and set password in attrs
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

                ou = getattr(user.partner_id, 'rotary_club_id', None)
                if ou and getattr(ou, 'club_id', False):
                    attrs["ou"] = [str(ou.club_id).encode()]

                rotary_id = extract_rotary_id(login, last_name)
                if rotary_id:
                    attrs["employeeNumber"] = [rotary_id.encode()]

                dn = f'uid={login}, {confd["ldap_base"]}'
                created, message = self._create_ldap_user(conf, dn, attrs)
                if created:
                    return True, message
                return False, message

            return False, "User not found in LDAP directory."

        # Existing DN → set password via python-ldap
        try:
            conn = self._pyldap_connect(conf)
            conn.simple_bind_s(admindn, adminpw)
            conn.passwd_s(dn, None, new_passwd)  # admin reset (old password None)
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

    # --------------------------- HELPERS (LDAP-first creation) ---------------------------
    def _ldap_attr_text(self, attrs, key, default=""):
        """Return first value of attrs[key] as text."""
        try:
            vals = attrs.get(key) or []
            if not vals:
                return default
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return default

    def _get_uid_from_attrs(self, attrs):
        """Return uid (string) from LDAP attrs, or ''."""
        try:
            vals = attrs.get('uid') or []
            if not vals:
                return ''
            v = vals[0]
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return ''

    def _ldap_find_by_attrs(self, conf, attrs):
        """
        Try to find an LDAP entry using given attributes (dict with bytes lists).
        Priority: mail -> cn (exact) -> givenName+sn (both).
        Returns (dn, entry) or (False, False) if not found.
        """
        confd = self._as_dict(conf)

        def _query_filter(flt):
            try:
                return self._query(confd, flt)
            except Exception:
                return []

        # 1) by mail
        mail = self._ldap_attr_text(attrs, 'mail').strip()
        if mail:
            f = filter_format('(&(objectClass=inetOrgPerson)(mail=%s))', (mail,))
            res = [r for r in _query_filter(f) if r and r[0]]
            if res:
                for r in res:
                    if r[0]:
                        return r[0], r

        # 2) by cn
        cn = (self._ldap_attr_text(attrs, 'cn') or '').strip()
        if cn:
            f = filter_format('(&(objectClass=inetOrgPerson)(cn=%s))', (cn,))
            res = [r for r in _query_filter(f) if r and r[0]]
            if res:
                return res[0][0], res[0]

        # 3) by givenName + sn
        given = (self._ldap_attr_text(attrs, 'givenname') or '').strip()
        sn = (self._ldap_attr_text(attrs, 'sn') or '').strip()
        if given and sn:
            f = filter_format('(&(objectClass=inetOrgPerson)(givenName=%s)(sn=%s))', (given, sn))
            res = [r for r in _query_filter(f) if r and r[0]]
            if res:
                return res[0][0], res[0]

        return False, False
    # -------------------------------------------------------------------------

    # ---------------------- LDAP-first: REPLACE _get_or_create_user ----------------------
    def _get_or_create_user(self, conf, login, ldap_entry):
        """
        LDAP-first policy:

        - If Odoo user (by login) exists → return (id, True).
        - Else try LDAP by email/name (from provided attrs); if found:
            * Reuse LDAP uid as login.
            * If Odoo user by email exists → return it (align login).
            * Else ensure partner, then create user attached to that partner.
        - Else try LDAP by uid (login).
        - Else create LDAP entry (from provided attrs), then partner, then user.

        Returns (user_id_or_error, existing_user_bool).
        """
        env = self.env  # keep Environment; sudo on model operations where needed
        existing_user = False
        confd = self._as_dict(conf)

        # Normalize login
        login_norm = tools.ustr((login or "")).lower().strip()

        # (1) Existing Odoo user by login?
        env.cr.execute("SELECT id, active FROM res_users WHERE lower(login)=%s", (login_norm,))
        res = env.cr.fetchone()
        if res and res[1]:
            existing_user = True
            return res[0], existing_user

        # Prepare mapped values (company_id, email fallback, etc.)
        mapped_vals = self._map_ldap_attributes(conf, login_norm, ldap_entry) or {}
        company_id = mapped_vals.get('company_id') or env.company.id

        # helper: create user attached to a partner with a specific final_login
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

            # Template user support
            template_id = None
            v = confd.get('user')
            if isinstance(v, (list, tuple)) and v:
                template_id = v[0]
            elif isinstance(v, int):
                template_id = v

            if template_id:
                return SudoUser.browse(template_id).copy(default=vals).id
            return SudoUser.create(vals).id

        # Attributes passed by caller (used for email/name lookup)
        attrs_provided = (ldap_entry[1] if ldap_entry else {}) or {}

        # (2) LDAP lookup by email/name first; if found, REUSE uid as login
        dn_found, entry_found = self._ldap_find_by_attrs(confd, attrs_provided)
        if entry_found:
            ldap_attrs = entry_found[1]
            ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or login_norm).lower().strip()
            email = (self._ldap_attr_text(ldap_attrs, 'mail') or mapped_vals.get('email') or '').strip().lower()

            # Prefer existing Odoo user by email
            if email:
                user_by_email = env['res.users'].with_context(active_test=False).sudo().search([('email', '=', email)], limit=1)
                if user_by_email and user_by_email.active:
                    existing_user = True
                    if (user_by_email.login or '').lower() != ldap_uid:
                        user_by_email.sudo().write({'login': ldap_uid})
                    return user_by_email.id, existing_user

            # No user -> ensure partner, then create user with LDAP uid
            partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
            user_id = _create_user_for_partner(partner, ldap_uid)
            return user_id, existing_user

        # (3) Not found by email/name → try LDAP by uid (original login)
        dn_found, entry_found = self._get_entry(confd, login_norm)
        if entry_found:
            ldap_attrs = entry_found[1]
            ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or login_norm).lower().strip()
            email = (self._ldap_attr_text(ldap_attrs, 'mail') or mapped_vals.get('email') or '').strip().lower()

            if email:
                user_by_email = env['res.users'].with_context(active_test=False).sudo().search([('email', '=', email)], limit=1)
                if user_by_email and user_by_email.active:
                    existing_user = True
                    if (user_by_email.login or '').lower() != ldap_uid:
                        user_by_email.sudo().write({'login': ldap_uid})
                    return user_by_email.id, existing_user

            partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
            user_id = _create_user_for_partner(partner, ldap_uid)
            return user_id, existing_user

        # (4) No LDAP entry at all → create LDAP then partner+user
        try:
            dn_provided, attrs_provided = ldap_entry or (None, None)
            if not dn_provided or not isinstance(attrs_provided, dict):
                return _("Missing LDAP attributes for new entry"), existing_user

            created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
            if not created:
                return _("LDAP create failed: %s") % msg, existing_user

            partner = ensure_partner_from_ldap(env.sudo(), attrs_provided, company_id)
            user_id = _create_user_for_partner(partner, login_norm)
            return user_id, existing_user

        except Exception as e:
            return _("LDAP create error: %s") % (e,), existing_user
    # ------------------------------------------------------------------------------------

    def _create_ldap_user(self, conf, user_dn, attributes):
        """Create the LDAP inetOrgPerson entry using admin bind."""
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
        """
        Map LDAP attributes to Odoo user values; ensure company_id is an ID
        and login is normalized to lowercase.
        """
        values = super()._map_ldap_attributes(conf, login, ldap_entry) or {}

        # Normalize company_id (record or (id, name) → id)
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

        # Ensure login is lowercase (avoids duplicates by case)
        if values.get('login'):
            values['login'] = tools.ustr(values['login']).lower().strip()
        else:
            values['login'] = tools.ustr(login).lower().strip()

        return values
