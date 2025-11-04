# -*- coding: utf-8 -*-
"""
Signup controller + LDAP helper for rotary_signup module.

Flow:
 - If an LDAP entry exists for the submitted email -> use LDAP attrs -> ensure partner -> create Odoo user (linked)
 - If no LDAP entry -> create LDAP entry -> ensure partner -> create Odoo user
Matching is always done by email.
If python-ldap is not installed, the module will fall back to Odoo-only user creation.
"""
import logging
import random
from datetime import date
import werkzeug

from odoo import api, fields, models, tools, SUPERUSER_ID, _, http
from odoo.http import request
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Try lazy import of python-ldap to avoid import-time crash if missing.
try:
    import ldap
    import ldap.modlist as modlist
except Exception:
    ldap = None
    modlist = None
    _logger.debug("python-ldap not available at import time; LDAP operations will be disabled")

SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang',
    'first_name', 'last_name', 'rotary_id', 'rotary_club', 'rotary_club_id',
    'club_type', 'program_type', 'program_type_id',
}

_PROGRAM_TYPE_NAMES = ["None", "Rotary", "Rotaract", "Interact", "Rota-Kids"]


def _program_type_objects():
    """Return lightweight mock objects for static program type dropdown."""
    return [{'id': i, 'name': n} for i, n in enumerate(_PROGRAM_TYPE_NAMES, start=1)]


# -----------------------------
# Helpers
# -----------------------------
def generate_random_number(min_length, max_length):
    return random.randint(10 ** (min_length - 1), (10 ** max_length) - 1)


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
    if env['res.users'].with_context(active_test=False).search([('email', 'ilike', email)], limit=1):
        return False, _("This email is already registered.")
    if not (first_name or "").strip():
        return False, _("First name is required.")
    if not (last_name or "").strip():
        return False, _("Last name is required.")
    return True, ""


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
    """Signup flow using ldap_reset_password templates."""

    @http.route('/clubs/by_program', type='json', auth='public', csrf=False, website=True)
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
    @http.route('/web/signup_non_member', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup_non_member(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext.setdefault('program_types', [])
        qcontext.setdefault('clubs', [])

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if request.httprequest.method == 'POST':
            # Use request.cr which is safe in controller request context
            env = api.Environment(request.cr, SUPERUSER_ID, {})
            try:
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                ldap_conf = env['res.company.ldap'].search([], limit=1)
                if not ldap_conf:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup_non_member', qcontext)

                sn = (qcontext.get('last_name') or '').strip()
                fn = (qcontext.get('first_name') or '').strip()
                rotary_id = str(generate_random_number(5, 8))
                login = (sn + rotary_id).lower()
                cn = f"{fn} {sn}".strip()

                # LDAP attributes we will provide if creating LDAP entry
                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "employeeNumber": [rotary_id.encode()],
                    "mail": [qcontext.get('email', '').encode()],
                    "userPassword": [qcontext.get('password', '').encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }

                # Construct DN to enable LDAP create when necessary
                ldap_base = getattr(ldap_conf, 'ldap_base', False) or ''
                dn = f"uid={login},{ldap_base}" if ldap_base else None

                # 1) Try to find/create user via LDAP model (this will check LDAP by email) - LDAP-first
                user = None
                try:
                    ldap_model = env['res.company.ldap'].sudo()
                    user_id, existing = ldap_model._get_or_create_user_tuple(ldap_conf, qcontext.get('email'), (dn, attrs))
                    if isinstance(user_id, int) and user_id:
                        user = env['res.users'].sudo().browse(user_id)
                except Exception as e:
                    _logger.debug("LDAP-backed user create failed (fall back to Odoo-only): %s", e)
                    user = None

                # If LDAP-backed creation didn't provide a user, fallback: ensure partner + create Odoo user
                partner = ensure_partner_from_ldap(env, attrs, ldap_conf.company.id if ldap_conf.company else env.company.id)
                if not user:
                    # use generated login as fallback local login
                    user = env['res.users'].sudo().create({'login': login, 'partner_id': partner.id, 'active': True, 'name': cn})

                # Write membership id if any
                if rotary_id.isdigit():
                    partner.write({'rotary_membership_id': rotary_id})

                # Assign Guests role
                role = env['res.users.role'].search([('name', '=', 'Guests')], limit=1)
                env['res.users.role.line'].search([('user_id', '=', user.id)]).unlink()
                if role:
                    env['res.users.role.line'].create({
                        'user_id': user.id,
                        'role_id': role.id,
                        'date_from': date.today(),
                        'date_to': date(2099, 12, 31),
                    })
                    user.set_groups_from_roles()

                return request.render('ldap_reset_password.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                env.cr.rollback()
                _logger.exception("Signup non-member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

        return request.render('ldap_reset_password.signup_non_member', qcontext)

    # --- Step 3: Member signup ---
    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext['program_types'] = _program_type_objects()

        # fallback club list for initial render
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if request.httprequest.method == 'POST':
            env = api.Environment(request.cr, SUPERUSER_ID, {})
            try:
                ok, msg = validate_signup_fields(env, qcontext.get('email'), qcontext.get('first_name'), qcontext.get('last_name'))
                if not ok:
                    qcontext['error'] = msg
                    return request.render('ldap_reset_password.signup', qcontext)

                ldap_conf = env['res.company.ldap'].search([], limit=1)
                if not ldap_conf:
                    qcontext['error'] = _("No LDAP configuration found.")
                    return request.render('ldap_reset_password.signup', qcontext)

                sn = (qcontext.get('last_name') or '').strip()
                fn = (qcontext.get('first_name') or '').strip()
                rotary_id = (qcontext.get('rotary_id') or '').strip()
                login = (sn + rotary_id).lower()
                cn = f"{fn} {sn}".strip()
                rotary_club_id = int(qcontext.get('rotary_club_id') or 0)

                # Build attrs (only include employeeNumber if provided)
                attrs = {
                    "uid": [login.encode()],
                    "givenname": [fn.encode()],
                    "cn": [cn.encode()],
                    "sn": [sn.encode()],
                    "ou": [str(rotary_club_id).encode()],
                    "mail": [qcontext.get('email', '').encode()],
                    "userPassword": [qcontext.get('password', '').encode()],
                    "objectclass": [b"top", b"inetOrgPerson"],
                }
                if rotary_id:
                    attrs['employeeNumber'] = [rotary_id.encode()]

                # Construct DN (so LDAP create can occur if needed)
                ldap_base = getattr(ldap_conf, 'ldap_base', False) or ''
                dn = f"uid={login},{ldap_base}" if ldap_base else None

                # 1) Try LDAP-backed create/find by email (give DN+attrs so creation is possible) - LDAP-first
                user = None
                try:
                    ldap_model = env['res.company.ldap'].sudo()
                    user_id, existing = ldap_model._get_or_create_user_tuple(ldap_conf, qcontext.get('email'), (dn, attrs))
                    if isinstance(user_id, int) and user_id:
                        user = env['res.users'].sudo().browse(user_id)
                except Exception as e:
                    _logger.debug("LDAP-backed create failed, will fallback to Odoo-only: %s", e)
                    user = None

                # 2) Ensure partner (from LDAP attrs) and create Odoo user if needed
                partner = ensure_partner_from_ldap(env, attrs, ldap_conf.company.id if ldap_conf.company else env.company.id)
                if not user:
                    user = env['res.users'].sudo().create({'login': login, 'partner_id': partner.id, 'active': True, 'name': cn})

                # Write club/membership/program on partner
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
                    partner.write(vals)

                # Assign Members role
                role = env['res.users.role'].search([('name', '=', 'Members')], limit=1)
                env['res.users.role.line'].search([('user_id', '=', user.id)]).unlink()
                if role:
                    env['res.users.role.line'].create({
                        'user_id': user.id,
                        'role_id': role.id,
                        'date_from': date.today(),
                        'date_to': date(2099, 12, 31),
                    })
                    user.set_groups_from_roles()

                return request.render('ldap_reset_password.web_thanks', {'message': _('You have created user: %s') % user.login})
            except Exception as e:
                env.cr.rollback()
                _logger.exception("Signup member exception: %s", e)
                qcontext['error'] = _("Could not create account. %s") % str(e)

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

    def _as_dict(self, conf):
        """Normalize conf record/dict to dict."""
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
            'user': getattr(conf, 'user', False),
            'company': (conf.company.id, conf.company.name) if getattr(conf, 'company', False) else False,
        }

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
        # set short timeouts
        try:
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
        except Exception:
            pass
        try:
            conn.set_option(ldap.OPT_TIMEOUT, 5)
        except Exception:
            pass
        try:
            conn.set_option(ldap.OPT_REFERRALS, 0)
        except Exception:
            pass
        if use_tls and port != 636:
            try:
                conn.start_tls_s()
            except Exception:
                _logger.warning("Failed to start TLS on LDAP connection")
        return conn

    def _create_ldap_user(self, conf, user_dn, attributes):
        """Create LDAP entry using python-ldap. Returns (created:bool, message:str)."""
        if ldap is None or modlist is None:
            return False, "python-ldap not installed"
        confd = self._as_dict(conf)
        admindn = confd.get('ldap_binddn') or ''
        adminpw = confd.get('ldap_password') or ''
        try:
            conn = self._pyldap_connect(confd)
            if admindn and adminpw:
                conn.simple_bind_s(admindn, adminpw)
            ldif = modlist.addModlist(attributes)
            conn.add_s(user_dn, ldif)
            conn.unbind_s()
            return True, 'Success'
        except ldap.ALREADY_EXISTS:
            return False, 'Already exists'
        except Exception as e:
            _logger.exception("_create_ldap_user failed: %s", e)
            return False, tools.ustr(e)

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
        """Find LDAP entry by email only (returns dn, entry)."""
        if ldap is None:
            return False, False
        confd = self._as_dict(conf)
        mail = (self._ldap_attr_text(attrs, 'mail') or '').strip()
        if not mail:
            return False, False
        try:
            f = f'(&(objectClass=inetOrgPerson)(mail={mail}))'
            conn = self._pyldap_connect(confd)
            if confd.get('ldap_binddn') and confd.get('ldap_password'):
                conn.simple_bind_s(confd.get('ldap_binddn'), confd.get('ldap_password'))
            results = conn.search_s(confd.get('ldap_base') or '', ldap.SCOPE_SUBTREE, f)
            conn.unbind_s()
            if results:
                for r in results:
                    if r and r[0]:
                        return r[0], r
        except Exception:
            _logger.exception("_ldap_find_by_attrs failed for mail=%s", mail)
            return False, False
        return False, False

    def _get_or_create_user_tuple(self, conf, login, ldap_entry):
        """
        Return (user_id:int, existing:bool).
        Checks LDAP first by email (login param is treated as email).
        If LDAP entry exists -> create/reuse partner and create user using mapped attrs.
        If LDAP entry missing and ldap_entry provided -> create LDAP entry then create Odoo user.
        """
        env = self.env
        confd = self._as_dict(conf)
        requested_email = tools.ustr(login or "").strip().lower()

        # If python-ldap is not present, do not crash: return 0 -> fallback to Odoo creation
        if ldap is None:
            _logger.debug("python-ldap not available: skipping LDAP-backed create")
            return 0, False

        # --- LDAP-first: try to find an LDAP entry by email (attrs from controller may be provided) ---
        attrs_from_controller = (ldap_entry[1] if ldap_entry else {}) or {}
        dn_found, entry_found = self._ldap_find_by_attrs(confd, attrs_from_controller)

        if entry_found:
            ldap_attrs = entry_found[1]
            ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or requested_email).strip().lower()
            U = env['res.users'].with_context(active_test=False).sudo()
            # If an Odoo user already exists with that LDAP uid, return it
            user_by_uid = U.search([('login', '=ilike', ldap_uid)], limit=1)
            if user_by_uid and user_by_uid.active:
                return user_by_uid.id, True

            # Ensure or create partner from LDAP attrs (company from confd if set)
            try:
                company_id = confd.get('company') and confd['company'][0] or env.company.id
            except Exception:
                company_id = env.company.id
            partner = None
            try:
                partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
            except Exception:
                partner = None

            # Create Odoo user using mapped LDAP attributes
            final_login = ldap_uid
            SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
            vals = self._map_ldap_attributes(conf, ldap_uid, entry_found) or {}
            vals.update({'login': final_login, 'partner_id': partner.id if partner else False, 'active': True, 'totp_enabled': False})
            vals.pop('email', None)
            try:
                user = SudoUser.create(vals)
                return user.id, False
            except Exception as e:
                _logger.exception("Failed to create Odoo user from LDAP attrs: %s", e)
                # Fall through to allow other creation paths
                return 0, False

        # --- If LDAP entry not found, check if an Odoo user already exists with requested_email and return it ---
        try:
            env.cr.execute("SELECT id FROM res_users WHERE lower(login)=%s", (requested_email,))
            row = env.cr.fetchone()
            if row:
                return row[0], True
        except Exception:
            # ignore DB errors here; proceed to creation paths
            pass

        # --- If controller gave a (dn, attrs), create LDAP entry then create Odoo user from those attrs ---
        dn_provided, attrs_provided = ldap_entry or (None, None)
        if dn_provided and isinstance(attrs_provided, dict):
            created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
            if not created:
                _logger.warning("LDAP create failed: %s", msg)
                return 0, False

            new_uid = (self._get_uid_from_attrs(attrs_provided) or requested_email).strip().lower()
            try:
                company_id = confd.get('company') and confd['company'][0] or env.company.id
            except Exception:
                company_id = env.company.id
            partner = None
            try:
                partner = ensure_partner_from_ldap(env, attrs_provided, company_id)
            except Exception:
                partner = None
            final_login = new_uid
            SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
            vals = self._map_ldap_attributes(conf, final_login, (dn_provided, attrs_provided)) or {}
            vals.update({'login': final_login, 'partner_id': partner.id if partner else False, 'active': True, 'totp_enabled': False})
            vals.pop('email', None)
            try:
                user = SudoUser.create(vals)
                return user.id, False
            except Exception as e:
                _logger.exception("Failed to create Odoo user after LDAP creation: %s", e)
                return 0, False

        # Nothing found and nothing created
        return 0, False
