# -*- coding: utf-8 -*-
import ldap
import ldap.modlist as modlist
from ldap.filter import filter_format

from odoo import api, fields, models, tools, http, SUPERUSER_ID, _
from ..utils import ensure_partner_from_ldap
import logging

_logger = logging.getLogger(__name__)

class CompanyLDAP(models.Model):
    _inherit = 'res.company.ldap'

    # ------- ldap helpers -------
    def _pyldap_connect(self, conf):
        host = getattr(conf, "ldap_server", None) or (conf.get("ldap_server") if isinstance(conf, dict) else "127.0.0.1")
        port = int(getattr(conf, "ldap_server_port", None) or (conf.get("ldap_server_port") if isinstance(conf, dict) else 389))
        use_tls = bool(getattr(conf, "ldap_tls", None) if not isinstance(conf, dict) else conf.get("ldap_tls", False))
        scheme = "ldaps" if port == 636 else "ldap"
        uri = f"{scheme}://{host}:{port}"
        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        for opt, val in [(ldap.OPT_NETWORK_TIMEOUT, 5), (ldap.OPT_TIMEOUT, 5), (ldap.OPT_REFERRALS, 0)]:
            try:
                conn.set_option(opt, val)
            except Exception:
                pass
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
            'create_user': conf.create_user,
            'user': getattr(conf.user, 'id', False),
            'company': (conf.company.id, conf.company.name) if conf.company else False,
        }

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

    def _get_entry(self, conf, login):
        confd = self._as_dict(conf)
        dn = entry = False
        try:
            fexpr = filter_format(confd['ldap_filter'], (login,))
        except Exception:
            _logger.warning("Could not format LDAP filter. Your filter should contain one '%%s'.")
            fexpr = False
        if fexpr:
            results = self._query(confd, tools.ustr(fexpr))
            results = [r for r in results if r[0]]
            for r in results:
                if len(r[1].get('uid', [])) == 1:
                    entry = r
                    dn = r[0]
                    break
        return dn, entry

    def _ldap_find_by_email(self, conf, email):
        if not email:
            return False, False
        confd = self._as_dict(conf)
        try:
            results = self._query(confd, filter_format('(&(objectClass=inetOrgPerson)(mail=%s))', (email,)))
            results = [r for r in results if r and r[0]]
            if results:
                return results[0][0], results[0]
        except Exception:
            return False, False
        return False, False

    # ------- password change (admin bind) -------
    def _change_password_admin_exceptions(self, conf, login, new_passwd):
        changed = False
        message = ""
        confd = self._as_dict(conf)

        dn, entry = self._get_entry(conf, login)
        admindn = confd['ldap_binddn']; adminpw = confd['ldap_password']

        if not dn:
            env = api.Environment(http.request.cr, SUPERUSER_ID, {})
            user = env['res.users'].search([('login', '=', login)], limit=1)
            if user:
                full_name = (user.partner_id.name or '').strip() or login
                parts = full_name.split()
                first_name = parts[0] if parts else 'First'
                last_name = parts[-1] if len(parts) > 1 else 'Last'
                attrs = {
                    "uid": [login.encode()], "givenname": [first_name.encode()],
                    "cn": [full_name.encode()], "sn": [last_name.encode()],
                    "userPassword": [new_passwd.encode()], "objectclass": [b"top", b"inetOrgPerson"],
                }
                email = getattr(user.partner_id, 'email', None)
                if email:
                    attrs["mail"] = [email.encode()]
                dn = f'uid={login}, {confd["ldap_base"]}'
                created, message = self._create_ldap_user(confd, dn, attrs)
                return (True, message) if created else (False, message)
            return False, "User not found in LDAP directory."

        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(admindn, adminpw)
            conn.passwd_s(dn, None, new_passwd)
            changed = True; message = 'Success'
            conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            message = 'An LDAP exception occurred: ' + str(e)
        except ldap.LDAPError as e:
            message = 'An LDAP exception occurred: ' + str(e)
        return changed, message

    # ------- user creation logic used by signup -------
    def _get_or_create_user(self, conf, login, ldap_entry):
        user_id, _existing = self._get_or_create_user_tuple(conf, login, ldap_entry)
        return user_id

    def _get_or_create_user_tuple(self, conf, login, ldap_entry):
        env = self.env
        confd = self._as_dict(conf)
        requested_email = tools.ustr(login or "").strip().lower()

        env.cr.execute("SELECT id FROM res_users WHERE lower(login)=%s", (requested_email,))
        row = env.cr.fetchone()
        if row:
            return row[0], True

        mapped_vals = self._map_ldap_attributes(conf, requested_email, ldap_entry) or {}
        company_id = mapped_vals.get('company_id') or env.company.id

        def _unique_login(env_, desired: str) -> str:
            base = tools.ustr(desired or '').strip().lower() or "user"
            U = env_['res.users'].with_context(active_test=False).sudo()
            if not U.search([('login', '=ilike', base)], limit=1):
                return base
            i = 2
            while True:
                cand = f"{base}-{i}"
                if not U.search([('login', '=ilike', cand)], limit=1):
                    return cand
                i += 1

        def _create_user_for_partner(partner, desired_login):
            final_login = _unique_login(env, desired_login)
            SudoUser = env['res.users'].with_context(no_reset_password=True).sudo()
            vals = dict(mapped_vals)
            vals.update({
                'login': final_login,
                'partner_id': partner.id,
                'active': True,
                'totp_enabled': False,
            })
            vals.pop('email', None)
            user = SudoUser.create(vals)
            return user.id, final_login

        attrs_from_controller = (ldap_entry[1] if ldap_entry else {}) or {}
        mail = (self._ldap_attr_text(attrs_from_controller, 'mail') or requested_email).strip().lower()
        _dn, entry_found = self._ldap_find_by_email(confd, mail)

        if entry_found:
            ldap_attrs = entry_found[1]
            ldap_uid = (self._get_uid_from_attrs(ldap_attrs) or requested_email).strip().lower()

            U = env['res.users'].with_context(active_test=False).sudo()
            user_by_uid = U.search([('login', '=ilike', ldap_uid)], limit=1)
            if user_by_uid and user_by_uid.active:
                return user_by_uid.id, True

            partner = ensure_partner_from_ldap(env, ldap_attrs, company_id)
            user_id, _ = _create_user_for_partner(partner, ldap_uid)
            return user_id, False

        dn_provided, attrs_provided = ldap_entry or (None, None)
        if not dn_provided or not isinstance(attrs_provided, dict):
            return 0, False

        created, msg = self._create_ldap_user(confd, dn_provided, attrs_provided)
        if not created:
            _logger.warning("LDAP create failed: %s", msg)
            return 0, False

        new_uid = (self._get_uid_from_attrs(attrs_provided) or requested_email).strip().lower()
        partner = ensure_partner_from_ldap(env, attrs_provided, company_id)
        user_id, _ = _create_user_for_partner(partner, new_uid)
        return user_id, False

    def _create_ldap_user(self, conf, user_dn, attributes):
        created = False
        message = ""
        confd = self._as_dict(conf)
        admindn = confd['ldap_binddn']; adminpw = confd['ldap_password']
        try:
            conn = self._pyldap_connect(confd)
            conn.simple_bind_s(admindn, adminpw)
            conn.add_s(user_dn, modlist.addModlist(attributes))
            created = True; message = 'Success'
            conn.unbind_s()
        except ldap.INVALID_CREDENTIALS as e:
            message = 'An LDAP exception occurred: ' + str(e)
        except ldap.LDAPError as e:
            if e.args and isinstance(e.args[0], dict) and e.args[0].get('desc') == 'Already exists':
                message = 'The LDAP entry already exists: ' + str(e)
            else:
                message = 'An LDAP exception occurred: ' + str(e)
        return created, message

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        values = super()._map_ldap_attributes(conf, login, ldap_entry) or {}
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
