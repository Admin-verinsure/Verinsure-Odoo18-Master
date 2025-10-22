# -*- coding: utf-8 -*-
from odoo import tools
from odoo.exceptions import ValidationError

def ensure_partner_from_ldap(env, attrs, company_id):
    """
    Idempotent partner lookup/create by LDAP attrs.
    If a unique-email constraint/validation fires, reuse the existing partner.
    """
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
    email_norm = email.lower()
    cn = (_attr(attrs, 'cn') or "").strip()
    given = (_attr(attrs, 'givenname') or "").strip()
    sn = (_attr(attrs, 'sn') or "").strip()
    name = cn or (f"{given} {sn}".strip()) or "New Contact"

    P = env['res.partner'].with_context(active_test=False).sudo()

    partner = False
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

    try:
        return P.create(vals)
    except ValidationError as ve:
        msg = tools.ustr(ve).lower()
        if 'already used' in msg or ('unique' in msg and 'email' in msg):
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if not p and email:
                try:
                    env.cr.execute(
                        "SELECT id FROM res_partner WHERE lower(email)=%s ORDER BY active DESC LIMIT 1",
                        (email_norm,)
                    )
                    r = env.cr.fetchone()
                    if r:
                        p = P.browse(r[0])
                except Exception:
                    pass
            if p:
                return p
        raise
    except Exception as e:
        msg = tools.ustr(e).lower()
        if 'unique' in msg and 'email' in msg:
            p = P.search(['|', ('email_normalized', '=', email_norm), ('email', '=', email)], limit=1)
            if p:
                return p
        raise
