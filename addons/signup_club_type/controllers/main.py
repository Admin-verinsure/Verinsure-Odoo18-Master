from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo import http
from odoo.http import request


class AuthSignupHomeExtended(AuthSignupHome):

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, csrf=False)
    def web_auth_signup(self, *args, **kw):
        """
        Serve the signup page using ldap_reset_password.signup
        and include program_types + clubs in the qcontext.
        """

        # Start from the same context logic Odoo normally uses
        qcontext = self.get_auth_signup_qcontext()

        # Your original rotary_id -> rotary_org_id mapping (kept from your code)
        if 'error' not in qcontext and 'rotary_id' in qcontext:
            qcontext['rotary_org_id'] = qcontext.get('rotary_id')

        # Pull program types for the Program Type dropdown
        # (this is what drives <t t-if="program_types"> in the template)
        try:
            qcontext['program_types'] = request.env['program.type'].sudo().search([], order='name')
        except Exception:
            # Fail safe: empty recordset so template t-if is False
            qcontext['program_types'] = request.env['ir.model'].sudo().browse([])

        # Pull clubs for initial render
        # This is a fallback list. Your XML override will later refine it
        # to filter by the chosen program when the form posts back.
        partners_club_name_not_empty = request.env['res.partner'].sudo().search([('club_name', '!=', '')])
        qcontext['clubs'] = [p for p in partners_club_name_not_empty if p.club_name]

        # Render your custom signup template (not the stock auth_signup one)
        resp = request.render('ldap_reset_password.signup', qcontext)
        resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    def _prepare_signup_values(self, qcontext):
        """Pass rotary_id through for account creation."""
        res = super(AuthSignupHomeExtended, self)._prepare_signup_values(qcontext)
        if 'rotary_id' in qcontext:
            res['rotary_org_id'] = qcontext['rotary_id']
        return res
