# -*- coding: utf-8 -*-
"""
Signup controller + LDAP helper for rotary_signup module.

Behavior aligned with the older, working code:
 - Match in LDAP by email.
 - Use LDAP uid as Odoo login (lowercased, sanitized).
 - If LDAP entry exists for submitted email → ensure partner → create Odoo user linked to LDAP uid.
 - If no LDAP entry → create LDAP entry (WITH userPassword) → ensure partner → create Odoo user.
 - No passwd_s after creation (password is set during LDAP add).
 - DN building uses escape_dn_chars; uid is sanitized (collision fallback still retained).
 - Public POST routes use csrf=False to match old behavior.
 - Password strength + confirmation checks.
"""
import logging
import random
import re
from datetime import date

import werkzeug

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Lazy import python-ldap to avoid import-time crash if missing
try:
    import ldap
    import ldap.modlist as modlist
    from ldap.filter import filter_format
    try:
        from ldap.dn import escape_dn_chars
    except Exception:
        def escape_dn_chars(s):  # fallback no-op
            return s
except Exception:
    ldap = None
    modlist = None
    filter_format = None
    def escape_dn_chars(s):  # fallback no-op
        return s
    _logger.debug("python-ldap not available at import time; LDAP operations will be disabled")

try:
    # For race-safe create retry
    from psycopg2 import IntegrityError
except Exception:  # pragma: no cover
    IntegrityError = Exception

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

_PROGRAM_TYPE_NAMES = ["None", "Rotary", "Rotaract", "Interact", "Rota-Kids"]

_UID_RE = re.compile(r'^[a-z0-9._-]{3,64}$')


def _program_type_objects():
    """Return lightweight mock objects for static program type dropdown."""
    return [{'id': i, 'name': n} for i, n in enumerate(_PROGRAM_TYPE_NAMES, start=1)]


# -----------------------------
# Helpers
# -----------------------------
def generate_random_number(min_length, max_length):
    return random.randint(10 ** (min_length - 1), (10 ** max_length) - 1)


def sanitize_uid(uid_raw: str) -> str:
    uid = (uid_raw or "").strip().lower()
    uid = re.sub(r'[^a-z0-9._-]+', '', uid)
    return uid[:64] or "user"


def check_password_strength(pw: str) -> bool:
    pw = pw or ""
    if len(pw) < 10:
        return False
    classes = sum(bool(re.search(r, pw)) for r in [r'[A-Z]', r'[a-z]', r'\d', r'[^\w\s]'])
    return classes >= 3


def _email_is_valid(email):
    email = (email or "").strip()
    try:
        re_ = getattr(tools, "single_email_re", None)
        if re_:
            return bool(re_.match(email))
    except Exception:
        pass
    return "@" in email and "." in email.split("@")[-1]


def _email_norm(email: str) -> str:
    return (email or "").strip().lower()


# OLD behavior: only block if a USER already has that email (not partners),
# and use ILIKE to be lenient like the working version.
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


def _create_user_with_retry(env, base_vals, base_login):
    """
    Create res.users with race-safe unique login retry.
    """
    SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
    i = 1
    while True:
        final_login = base_login if i == 1 else f"{base_login}-{i}"
        vals = dict(base_vals, login=final_login)
        try:
            with env.cr.savepoint():
                user = SudoUser.create(vals)
            return user
        except IntegrityError:
            i += 1


def ensure_partner_from_ldap(env, attrs, company_id):
    """Ensure partner record exists for given LDAP attributes (idempotent)."""
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
    email_norm = (email or "").lower()
    cn = (_attr(attrs, 'cn') or "").strip()
    given = (_attr(attrs, 'givenname') or "").strip()
    sn = (_attr(attrs, 'sn') or "").strip()
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()
    partner = False

    try:
        if email:
            partner = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if not partner:
                try:
                    env.cr.execute(
                        "SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1",
                        (email_norm,)
                    )
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
            if company_id and getattr(partner, 'company_id', False) and partner.company_id.id != company_id:
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
    except ValidationError as ve:
        # Try to recover from unique email race by returning existing partner
        msg = tools.ustr(ve).lower()
        if 'already used' in msg or ('unique' in msg and 'email' in msg):
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if p:
                return p
        raise
    except Exception as e:
        env.cr.rollback()
        _logger.warning("ensure_partner_from_ldap() failed: %s", e)
        raise


# -----------------------------
# Signup Controller
# -----------------------------
from odoo.addons.auth_signup.controllers.main import AuthSignupHome as AuthSignupController


class LDAPSignupController(AuthSignupController):
    """Signup flow using ldap_reset_password templates (CSRF disabled to match old flow)."""

    @http.route('/clubs/by_program', type='json', auth='public', website=True)  # CSRF enabled for JSON-RPC
    def clubs_by_program(self, program_type=None, **kw):
        """Return Rotary clubs filtered by program type (AJAX endpoint)."""
        if not program_type:
            return []

        try:
            env = request.env['res.partner'].sudo()
            domain = [('active', '=', True)]
            if str(program_type).isdigit():
                domain.append(('program_type_id', '=', int(program_type)))
            else:
                domain.append(('club_type', '=', program_type))
            clubs = env.search_read(domain, ['id', 'club_name', 'name'], order='club_name')
            return [{'id': c['id'], 'name': c.get('club_name') or c['name']} for c in clubs]
        except Exception as e:
            request.env.cr.rollback()
            _logger.exception("Club lookup error: %s", e)
            return []

    # --- Step 1 ---
    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kwargs):
        qcontext = self.get_auth_signup_qcontext()
        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])
        return request.render('ldap_reset_password.signup_is_member', qcontext)

    # --- Step 2: Non-member signup ---
    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)  # <-- match old
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext.setdefault('program_types', [])
        qcontext.setdefault('clubs', [])

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if request.httprequest.method == 'POST':
            env = request.env  # use recordset-level sudo where needed
            try:
                ok, msg = validate_signup_fields(env.sudo(), qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                pw = (qcontext.get('password') or '').strip()
                cpw = (qcontext.get('confirm_password') or '').strip()
                if not pw or not cpw or pw != cpw:
                    qcontext['error'] = _("Passwords do not match.")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)
                if not check_password_strength(pw):
                    qcontext['error'] = _("Password too weak. Use at least 10 chars with upper/lower/digit/symbol (3 classes).")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                # Prefer company-specific LDAP config
                company = env.company
                ldap_conf = env['res.company.ldap'].sudo().search([('company', '=', company.id)], limit=1) \
                            or env['res.company.ldap'].sudo().search([], limit=1)
                if not ldap_conf:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                sn = (qcontext.get('last_name') or '').strip()
                fn = (qcontext.get('first_name') or '').strip()
                email = _email_norm(qcontext.get('email'))
                rotary_id = str(generate_random_number(5, 8))

                proposed_uid = sanitize_uid((sn + rotary_id) or (email.split('@')[0] if '@' in email else 'user'))

                # Ensure ldap_base is present
                ldap_base = getattr(ldap_conf, 'ldap_base', False) or ''
                if not ldap_base:
                    qcontext['error'] = _("LDAP base DN is not configured. Please contact support.")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                dn = f"uid={escape_dn_chars(proposed_uid)},{ldap_base}"
                cn = f"{fn} {sn}".strip()

                # LDAP attributes WITH password (old behavior)
                attrs = {
                    "uid": [proposed_uid.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "employeeNumber": [rotary_id.encode()],
                    "mail": [email.encode()],
                    "userPassword": [pw.encode()],  # <-- set during add
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                # LDAP-backed: get/create user via model
                user = None
                try:
                    ldap_model = env['res.company.ldap'].sudo()
                    user_id, existing = ldap_model._get_or_create_user_tuple(ldap_conf, email, (dn, attrs))

                    # Old flow: if "existing", show error page
                    if existing:
                        return request.render('ldap_reset_password.web_error', {'message': _('Error: User already exists.')})

                    if isinstance(user_id, int) and user_id:
                        # Double-check LDAP has the entry; if missing, add now
                        dn_exist, entry_exist = ldap_model._ldap_find_by_attrs(ldap_conf, attrs)
                        if not entry_exist:
                            created, message = ldap_model._create_ldap_user(ldap_conf, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return request.render('ldap_reset_password.web_error', {'message': (message or '') + '.'})
                        user = request.env['res.users'].sudo().browse(user_id)
                    else:
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))
                        return request.render('ldap_reset_password.signup_non_member', qcontext)
                except Exception as e:
                    _logger.debug("LDAP-backed user create failed (fallback to Odoo-only): %s", e)
                    user = None

                # Ensure partner and create Odoo user if still missing
                partner = ensure_partner_from_ldap(env.sudo(), attrs, ldap_conf.company.id if ldap_conf.company else env.company.id)
                if not user:
                    base_vals = {
                        'partner_id': partner.id,
                        'active': True,
                        'name': cn,
                        'totp_enabled': False,
                    }
                    user = _create_user_with_retry(env, base_vals, proposed_uid)

                # Partner extras (guarded)
                try:
                    if rotary_id.isdigit():
                        partner.write({'rotary_membership_id': rotary_id})
                except Exception:
                    pass

                # Assign Guests role
                try:
                    role = env['res.users.role'].sudo().search([('name', '=', 'Guests')], limit=1)
                    env['res.users.role.line'].sudo().search([('user_id', '=', user.id)]).unlink()
                    if role:
                        env['res.users.role.line'].sudo().create({
                            'user_id': user.id,
                            'role_id': role.id,
                            'date_from': date.today(),
                            'date_to': date(2099, 12, 31),
                        })
                        user.set_groups_from_roles()
                except Exception:
                    _logger.warning("Role assignment (Guests) failed for user %s", user.id)

                return request.render('ldap_reset_password.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                env.cr.rollback()
                _logger.exception("Signup non-member exception: %s", e)
                qcontext['error'] = _("Could not create account. Please try again or contact support.")

        return request.render('ldap_reset_password.signup_non_member', qcontext)

    # --- Step 3: Member signup ---
    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)  # <-- match old
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext['program_types'] = _program_type_objects()

        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if request.httprequest.method == 'POST':
            env = request.env
            try:
                ok, msg = validate_signup_fields(env.sudo(), qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup', qcontext)

                pw = (qcontext.get('password') or '').strip()
                cpw = (qcontext.get('confirm_password') or '').strip()
                if not pw or not cpw or pw != cpw:
                    qcontext['error'] = _("Passwords do not match.")
                    return request.render('ldap_reset_password.signup', qcontext)
                if not check_password_strength(pw):
                    qcontext['error'] = _("Password too weak. Use at least 10 chars with upper/lower/digit/symbol (3 classes).")
                    return request.render('ldap_reset_password.signup', qcontext)

                # Prefer company-specific LDAP config
                company = env.company
                ldap_conf = env['res.company.ldap'].sudo().search([('company', '=', company.id)], limit=1) \
                            or env['res.company.ldap'].sudo().search([], limit=1)
                if not ldap_conf:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup', qcontext)

                sn = (qcontext.get('last_name') or '').strip()
                fn = (qcontext.get('first_name') or '').strip()
                email = _email_norm(qcontext.get('email'))
                rotary_id = (qcontext.get('rotary_id') or '').strip()
                rotary_club_id = int(qcontext.get('rotary_club_id') or 0)

                proposed_uid = sanitize_uid((sn + rotary_id) or (email.split('@')[0] if '@' in email else 'user'))

                # Ensure ldap_base is present
                ldap_base = getattr(ldap_conf, 'ldap_base', False) or ''
                if not ldap_base:
                    qcontext['error'] = _("LDAP base DN is not configured. Please contact support.")
                    return request.render('ldap_reset_password.signup', qcontext)

                dn = f"uid={escape_dn_chars(proposed_uid)},{ldap_base}"
                cn = f"{fn} {sn}".strip()

                attrs = {
                    "uid": [proposed_uid.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "ou": [str(rotary_club_id).encode()],
                    "mail": [email.encode()],
                    "userPassword": [pw.encode()],  # <-- set during add (old behavior)
                    "objectclass": [b"top", b"inetOrgPerson"],
                }
                if rotary_id:
                    attrs['employeeNumber'] = [rotary_id.encode()]

                user = None
                try:
                    ldap_model = env['res.company.ldap'].sudo()
                    user_id, existing = ldap_model._get_or_create_user_tuple(ldap_conf, email, (dn, attrs))

                    # Old flow: if "existing", show error page
                    if existing:
                        return request.render('ldap_reset_password.web_error', {'message': _('Error: User already exists.')})

                    if isinstance(user_id, int) and user_id:
                        # Double-check LDAP has the entry; if missing, add now
                        dn_exist, entry_exist = ldap_model._ldap_find_by_attrs(ldap_conf, attrs)
                        if not entry_exist:
                            created, message = ldap_model._create_ldap_user(ldap_conf, dn, attrs)
                            if not created and "Already exists" not in (message or ""):
                                request.env['res.users'].sudo().browse(user_id).unlink()
                                return request.render('ldap_reset_password.web_error', {'message': (message or '') + '.'})
                        user = request.env['res.users'].sudo().browse(user_id)
                    else:
                        qcontext['error'] = _("Could not create a new account. " + str(user_id))
                        return request.render('ldap_reset_password.signup', qcontext)
                except Exception as e:
                    _logger.debug("LDAP-backed create failed, fallback to Odoo-only: %s", e)
                    user = None

                partner = ensure_partner_from_ldap(env.sudo(), attrs, ldap_conf.company.id if ldap_conf.company else env.company.id)
                if not user:
                    base_vals = {
                        'partner_id': partner.id,
                        'active': True,
                        'name': cn,
                        'totp_enabled': False,
                    }
                    user = _create_user_with_retry(env, base_vals, proposed_uid)

                # Partner enrich
                vals = {}
                if rotary_club_id:
                    vals['rotary_club_id'] = rotary_club_id
                if rotary_id and rotary_id.isdigit():
                    vals['rotary_membership_id'] = rotary_id
                if qcontext.get('program_type_id'):
                    try:
                        vals['program_type_id'] = int(qcontext['program_type_id'])
                    except Exception:
                        vals['program_type_id'] = qcontext.get('program_type_id')
                if vals:
                    try:
                        partner.write(vals)
                    except Exception:
                        pass

                # Assign Members role
                try:
                    role = env['res.users.role'].sudo().search([('name', '=', 'Members')], limit=1)
                    env['res.users.role.line'].sudo().search([('user_id', '=', user.id)]).unlink()
                    if role:
                        env['res.users.role.line'].sudo().create({
                            'user_id': user.id,
                            'role_id': role.id,
                            'date_from': date.today(),
                            'date_to': date(2099, 12, 31),
                        })
                        user.set_groups_from_roles()
                except Exception:
                    _logger.warning("Role assignment (Members) failed for user %s", user.id)

                return request.render('ldap_reset_password.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                env.cr.rollback()
                _logger.exception("Signup member exception: %s", e)
                qcontext['error'] = _("Could not create account. Please try again or contact support.")

        return request.render('ldap_reset_password.signup', qcontext)

    # --- QContext Loader ---
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


# -----------------------------
# LDAP Company Extension (robust and lazy)
# -----------------------------
class CompanyLDAP(models.Model):
    _inherit = "res.company.ldap"

    # ---------- config normalization ----------
    def _as_dict(self, conf):
        """Normalize conf record/dict to dict (old behavior)."""
        if isinstance(conf, dict):
            return conf
        return {
            'ldap_filter': getattr(conf, 'ldap_filter', False),
            'ldap_base': getattr(conf, 'ldap_base', False),
            'ldap_binddn': getattr(conf, 'ldap_binddn', False),
            'ldap_password': getattr(conf, 'ldap_password', False),
            'ldap_server': getattr(conf, 'ldap_server', False),
            'ldap_server_port': getattr(conf, 'ldap_server_port', False),
            'ldap_tls': getattr(conf, 'ldap_tls', False),
            'create_user': getattr(conf, 'create_user', False),
            # return a primitive id (old flow expectation)
            'user': getattr(getattr(conf, 'user', False), 'id', False),
            # return a (id, name) tuple for company (old flow expectation)
            'company': (conf.company.id, conf.company.name) if getattr(conf, 'company', False) else False,
        }

    # ---------- connection ----------
    def _pyldap_connect(self, conf):
        """Create and return a python-ldap connection using conf dict (lazy import)."""
        if ldap is None:
            raise Exception("python-ldap module not installed; LDAP operations are disabled")
        confd = self._as_dict(conf)
        host = confd.get('ldap_server') or '127.0.0.1'
        port = int(confd.get('ldap_server_port') or 389)
        use_tls = bool(confd.get('ldap_tls') or False)
        scheme = "ldaps" if port == 636 else "ldap"
        uri = f"{scheme}://{host}:{port}"
        conn = ldap.initialize(uri)
        try:
            conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        except Exception:
            pass
        # short timeouts
        for opt, val in [
            (getattr(ldap, 'OPT_NETWORK_TIMEOUT', None), 5),
            (getattr(ldap, 'OPT_TIMEOUT', None), 5),
            (getattr(ldap, 'OPT_REFERRALS', None), 0),
        ]:
            try:
                if opt is not None:
                    conn.set_option(opt, val)
            except Exception:
                pass
        if use_tls and port != 636:
            try:
                conn.start_tls_s()
            except Exception:
                _logger.warning("Failed to start TLS on LDAP connection")
        return conn

    # ---------- read helpers ----------
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

    # ---------- search by email ----------
    def _ldap_find_by_email(self, conf, email: str):
        """Find LDAP entry by raw email string using Odoo's internal query path (returns dn, entry)."""
        email = (email or "").strip()
        if not email:
            return False, False
        confd = self._as_dict(conf)

        def _q(flt):
            try:
                return self._query(confd, flt)
            except Exception:
                return []

        try:
            flt = filter_format('(&(objectClass=inetOrgPerson)(mail=%s))', (email,)) if filter_format else f'(&(objectClass=inetOrgPerson)(mail={email}))'
        except Exception:
            flt = f'(&(objectClass=inetOrgPerson)(mail={email}))'

        res = [r for r in _q(flt) if r and r[0]]
        if res:
            return res[0][0], res[0]
        return False, False

    # ---------- search by attrs (email-only) ----------
    def _ldap_find_by_attrs(self, conf, attrs):
        mail = (self._ldap_attr_text(attrs, 'mail') or '').strip()
        if not mail:
            return False, False
        return self._ldap_find_by_email(conf, mail)

    # ---------- search by uid ----------
    def _ldap_find_by_uid(self, conf, uid_value: str):
        if ldap is None or not uid_value:
            return False, False
        confd = self._as_dict(conf)

        def _q(flt):
            try:
                return self._query(confd, flt)
            except Exception:
                return []
        try:
            flt = filter_format('(&(objectClass=inetOrgPerson)(uid=%s))', (uid_value,)) if filter_format else f'(&(objectClass=inetOrgPerson)(uid={uid_value}))'
            res = [r for r in _q(flt) if r and r[0]]
            if res:
                return res[0][0], res[0]
        except Exception:
            _logger.exception("_ldap_find_by_uid failed for uid=%s", uid_value)
        return False, False

    # ---------- create entry (KEEP password if provided) ----------
    def _create_ldap_user(self, conf, user_dn, attributes):
        """Create LDAP entry; keeps userPassword if present (old behavior)."""
        if ldap is None or modlist is None:
            return False, "python-ldap not installed"
        confd = self._as_dict(conf)
        admindn = confd.get('ldap_binddn') or ''
        adminpw = confd.get('ldap_password') or ''
        try:
            conn = self._pyldap_connect(confd)
            if admindn and adminpw:
                conn.simple_bind_s(admindn, adminpw)
            conn.add_s(user_dn, modlist.addModlist(attributes))  # DO NOT strip userPassword
            conn.unbind_s()
            return True, 'Success'
        except Exception as e:
            # Mirror older error surfacing; map Already exists if possible
            try:
                if hasattr(e, 'args') and e.args and isinstance(e.args[0], dict) and e.args[0].get('desc') == 'Already exists':
                    return False, 'Already exists'
            except Exception:
                pass
            return False, 'An LDAP exception occurred: ' + tools.ustr(e)

    # ---------- set password via passwd_s (NOT used by signup now, retained for compatibility) ----------
    def _set_ldap_password(self, conf, user_dn: str, new_password: str):
        if ldap is None:
            return False, "python-ldap not installed"
        if not new_password:
            return False, "Empty password"
        confd = self._as_dict(conf)
        try:
            conn = self._pyldap_connect(confd)
            if confd.get('ldap_binddn') and confd.get('ldap_password'):
                conn.simple_bind_s(confd.get('ldap_binddn'), confd.get('ldap_password'))
            conn.passwd_s(user_dn, None, new_password)  # server-side hashing
            conn.unbind_s()
            return True, "Success"
        except Exception as e:
            _logger.exception("_set_ldap_password failed: %s", e)
            return False, tools.ustr(e)

    # ---------- attribute mapping override (add company_id + normalize login) ----------
    def _map_ldap_attributes(self, conf, login, ldap_entry):
        """
        Align with older behavior: inject company_id and lowercased, trimmed login.
        """
        values = super()._map_ldap_attributes(conf, login, ldap_entry) or {}

        # Derive company_id from conf, else fall back to current env company
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

    # ---------- main create/find pipeline ----------
    def _get_or_create_user_tuple(self, conf, login, ldap_entry):
        """
        Always:
          - Match LDAP by email (login = email).
          - Use LDAP uid as Odoo login (sanitized).
        Returns (user_id:int, existing_user:bool).
        """
        env = self.env
        confd = self._as_dict(conf)
        requested_email = tools.ustr(login or "").strip().lower()
        if not requested_email:
            return 0, False
        if ldap is None:
            _logger.debug("python-ldap not available: skipping LDAP-backed create")
            return 0, False

        # Step 1: search LDAP strictly by the submitted email (not controller attrs)
        dn_found, entry_found = self._ldap_find_by_email(confd, requested_email)

        if dn_found and entry_found:
            ldap_attrs = entry_found[1] if isinstance(entry_found, tuple) else entry_found
            ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or requested_email).strip().lower()
            ldap_uid = sanitize_uid(ldap_uid) or requested_email
            final_login = ldap_uid

            # If Odoo user exists with this final_login, reuse
            U = env['res.users'].with_context(active_test=False).sudo()
            user = U.search([('login', '=ilike', final_login)], limit=1)
            if user:
                return user.id, True

            # Ensure partner
            try:
                company_id = confd.get('company') and confd['company'][0] or env.company.id
            except Exception:
                company_id = env.company.id
            partner = None
            try:
                partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
            except Exception as e:
                _logger.warning("Partner creation from LDAP failed: %s", e)

            # Create Odoo user (race-safe)
            vals = self._map_ldap_attributes(conf, final_login, (dn_found, ldap_attrs)) or {}
            vals.update({
                'partner_id': partner.id if partner else False,
                'active': True,
                'totp_enabled': False,
            })
            vals.pop('email', None)
            try:
                new_user = _create_user_with_retry(env, vals, final_login)
                _logger.info("Created Odoo user linked to existing LDAP uid=%s", new_user.login)
                return new_user.id, True
            except Exception as e:
                _logger.exception("Failed to create Odoo user from existing LDAP entry: %s", e)
                return 0, False

        # Step 2: no LDAP by email; maybe an Odoo user already exists with email login (legacy)
        try:
            env.cr.execute("SELECT id FROM res_users WHERE lower(login)=%s", (requested_email,))
            row = env.cr.fetchone()
            if row:
                return row[0], True
        except Exception:
            pass

        # Step 3: create LDAP entry using provided dn/attrs (after uid sanitation + collision checks)
        dn_provided, attrs_provided = ldap_entry or (None, None)
        if dn_provided and isinstance(attrs_provided, dict):
            # Re-check by email to avoid races
            re_dn, re_entry = self._ldap_find_by_email(confd, requested_email)
            if re_dn and re_entry:
                ldap_attrs = re_entry[1] if isinstance(re_entry, tuple) else re_entry
                ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or requested_email).strip().lower()
                ldap_uid = sanitize_uid(ldap_uid) or requested_email
                final_login = ldap_uid
                try:
                    company_id = confd.get('company') and confd['company'][0] or env.company.id
                except Exception:
                    company_id = env.company.id
                partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
                vals = self._map_ldap_attributes(conf, final_login, (re_dn, ldap_attrs)) or {}
                vals.update({'partner_id': partner.id if partner else False, 'active': True, 'totp_enabled': False})
                vals.pop('email', None)
                try:
                    new_user = _create_user_with_retry(env, vals, final_login)
                    return new_user.id, True
                except Exception as e:
                    _logger.exception("Failed to create Odoo user after race re-check: %s", e)
                    return 0, False

            # sanitize uid and DN (kept — harmless and avoids obvious conflicts)
            raw_uid = self._get_uid_from_attrs(attrs_provided) or requested_email
            safe_uid = sanitize_uid(raw_uid) or requested_email
            if safe_uid != raw_uid:
                attrs_provided = dict(attrs_provided)
                attrs_provided['uid'] = [safe_uid.encode()]
                base = confd.get('ldap_base') or ''
                dn_provided = "uid=" + escape_dn_chars(safe_uid) + ("," + base if base else "")

            # collision check on uid
            existing_dn, _ = self._ldap_find_by_uid(confd, safe_uid)
            if existing_dn:
                i = 2
                new_uid = f"{safe_uid}-{i}"
                while self._ldap_find_by_uid(confd, new_uid)[0]:
                    i += 1
                    new_uid = f"{safe_uid}-{i}"
                attrs_provided['uid'] = [new_uid.encode()]
                base = confd.get('ldap_base') or ''
                dn_provided = "uid=" + escape_dn_chars(new_uid) + ("," + base if base else "")
                safe_uid = new_uid

            created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
            if not created and 'Already exists' not in msg:
                _logger.warning("LDAP create failed: %s", msg)
                return 0, False

            # Create partner + Odoo user using uid as login
            new_uid = (self._get_uid_from_attrs(attrs_provided) or requested_email).strip().lower()
            final_login = sanitize_uid(new_uid) or requested_email

            try:
                company_id = confd.get('company') and confd['company'][0] or env.company.id
            except Exception:
                company_id = env.company.id

            partner = None
            try:
                partner = ensure_partner_from_ldap(env, attrs_provided, company_id)
            except Exception as e:
                _logger.warning("Partner create after new LDAP failed: %s", e)

            vals = self._map_ldap_attributes(conf, final_login, (dn_provided, attrs_provided)) or {}
            vals.update({
                'partner_id': partner.id if partner else False,
                'active': True,
                'totp_enabled': False,
            })
            vals.pop('email', None)
            try:
                new_user = _create_user_with_retry(env, vals, final_login)
                _logger.info("Created new LDAP + Odoo user for %s (uid=%s)", requested_email, new_user.login)
                return new_user.id, False
            except Exception as e:
                _logger.exception("Failed to create Odoo user after new LDAP: %s", e)
                return 0, False

        # Step 4: nothing we can do here
        _logger.warning("No LDAP or Odoo user could be created for %s", requested_email)
        return 0, False
