# your_module_name/controllers/main.py

from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo import http
from odoo.http import request

class SignupController(http.Controller):

    @http.route('/web/signup', type='http', auth='public', website=True)
    def custom_signup(self, **kwargs):
        env = request.env
        # Get all clubs filtered by type if provided
        club_type = kwargs.get("club_type")
        clubs = []
        if club_type:
            clubs = env['res.partner'].sudo().search([
                ('club_type', '=', club_type),
                ('club_name', '!=', False)
            ])
        values = {
            'clubs': clubs,
        }
        return request.render("ldap_reset_password.signup", values)
    
class AuthSignupHomeExtended(AuthSignupHome):

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False)
    def web_auth_signup(self, *args, **kw):
        qcontext = self.get_auth_signup_qcontext()
        if 'error' not in qcontext and 'rotary_id' in qcontext:
            qcontext['rotary_org_id'] = qcontext.pop('rotary_id')
        
        return super(AuthSignupHomeExtended, self).web_auth_signup(*args, **kw)

    def _prepare_signup_values(self, qcontext):
        """ Add rotary_id to the context for partner creation """
        res = super(AuthSignupHomeExtended, self)._prepare_signup_values(qcontext)
        if 'rotary_id' in qcontext:
            res['rotary_org_id'] = qcontext['rotary_id']
        return res