from odoo import http
from odoo.http import request

class RotarySignupController(http.Controller):

    @http.route('/web/is_member', type='http', auth='public', website=True)
    def is_member(self, **kw):
        """Landing page: Ask if user is Rotary member."""
        return request.render("rotary_signup.signup_is_member")

    @http.route('/web/signup', type='http', auth='public', website=True)
    def signup_member(self, **kw):
        """Signup form for Rotary members."""
        clubs = request.env['res.partner'].sudo().search([('is_rotary_club', '=', True)])
        program_types = request.env['program.type'].sudo().search([])

        return request.render("rotary_signup.signup", {
            'clubs': clubs,
            'program_types': program_types,
        })

    @http.route('/web/signup_non_member', type='http', auth='public', website=True)
    def signup_non_member(self, **kw):
        """Signup form for non-members."""
        clubs = request.env['res.partner'].sudo().search([('is_rotary_club', '=', True)])
        program_types = request.env['program.type'].sudo().search([])

        return request.render("rotary_signup.signup_non_member", {
            'clubs': clubs,
            'program_types': program_types,
        })
