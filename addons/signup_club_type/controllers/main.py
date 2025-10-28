# your_module_name/controllers/main.py

from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo import http
from odoo.http import request


class AuthSignupHomeExtended(AuthSignupHome):

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        """Render signup page using ldap_reset_password template instead of default."""
        # Replicate ldap_reset_password logic instead of falling back to stock auth_signup
        qcontext = request.env['ir.http']._prepare_qcontext()
        qcontext.update({k: v for (k, v) in request.params.items()})

        # Preserve the rotary_id remapping
        if 'error' not in qcontext and 'rotary_id' in qcontext:
            qcontext['rotary_org_id'] = qcontext.get('rotary_id')

        # Pull clubs and program types like ldap_reset_password does
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])

        # Render the custom signup template we actually want
        resp = request.render('ldap_reset_password.signup', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    def _prepare_signup_values(self, qcontext):
        """Add rotary_id to the context for partner creation."""
        res = super(AuthSignupHomeExtended, self)._prepare_signup_values(qcontext)
        if 'rotary_id' in qcontext:
            res['rotary_org_id'] = qcontext['rotary_id']
        return res
