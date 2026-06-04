# -*- coding: utf-8 -*-
import logging
from odoo import http, _
from odoo.http import request, Response
from odoo.addons.web.controllers.home import Home

_logger = logging.getLogger(__name__)

_PENDING_2FA_USER_KEY = '2fa_pending_user_id'


def _render_otp_page(values):
    """
    Render the OTP page bypassing website.layout entirely.
    We call ir.ui.view._render_template() with sudo() so the website
    module never gets a chance to inject its layout / singleton check.
    """
    html = request.env['ir.ui.view'].sudo()._render_template(
        'auth_2fa_email.otp_page', values
    )
    return Response(html, content_type='text/html;charset=utf-8', status=200)


class TwoFactorAuthController(Home):

    # ------------------------------------------------------------------
    # Step 1 – intercept the normal login POST
    # ------------------------------------------------------------------
    @http.route('/web/login', type='http', auth='none', methods=['GET', 'POST'], sitemap=False)
    def web_login(self, redirect=None, **kw):
        response = super().web_login(redirect=redirect, **kw)

        if request.httprequest.method != 'POST':
            return response

        uid = request.session.uid
        if not uid:
            return response

        user = request.env['res.users'].sudo().browse(uid)
        if not user.two_factor_enabled:
            return response

        # Park the uid and strip authentication from the session
        request.session[_PENDING_2FA_USER_KEY] = uid
        request.session.uid = None
        request.session.login = None
        request.session.password = ''

        # Generate & email OTP
        try:
            token = request.env['auth.otp'].sudo().generate_otp(uid)
            self._send_otp_email(user, token.otp_code)
        except Exception:
            _logger.exception('2FA: failed to send OTP email to user %s', uid)
            return _render_otp_page({
                'user_email': '',
                'redirect': redirect or '/odoo',
                'error': _('Could not send OTP email. Please contact your administrator.'),
                'success': False,
                'request': request,
            })

        target = '/web/login/otp?redirect=%s' % (redirect or '/odoo')
        return request.redirect(target)

    # ------------------------------------------------------------------
    # Step 2 – OTP verification page
    # ------------------------------------------------------------------
    @http.route('/web/login/otp', type='http', auth='none', methods=['GET', 'POST'], sitemap=False)
    def otp_verify(self, redirect='/odoo', **kw):
        pending_uid = request.session.get(_PENDING_2FA_USER_KEY)

        if not pending_uid:
            return request.redirect('/web/login')

        user = request.env['res.users'].sudo().browse(pending_uid)
        masked = self._mask_email(user.email or '')

        if request.httprequest.method == 'GET':
            return _render_otp_page({
                'user_email': masked,
                'redirect': redirect,
                'error': False,
                'success': False,
                'request': request,
            })

        # POST – verify code
        code = (kw.get('otp_code') or '').strip()
        valid = request.env['auth.otp'].sudo().verify_otp(pending_uid, code)

        if not valid:
            return _render_otp_page({
                'user_email': masked,
                'redirect': redirect,
                'error': _('Invalid or expired OTP. Please try again.'),
                'success': False,
                'request': request,
            })

        # Valid – finalise session
        request.session.pop(_PENDING_2FA_USER_KEY, None)
        request.session.uid = pending_uid
        request.session.login = user.login
        request.session.session_token = user._compute_session_token(request.session.sid)

        return request.redirect(redirect)

    # ------------------------------------------------------------------
    # Resend OTP
    # ------------------------------------------------------------------
    @http.route('/web/login/otp/resend', type='http', auth='none', methods=['GET'], sitemap=False)
    def otp_resend(self, redirect='/odoo', **kw):
        pending_uid = request.session.get(_PENDING_2FA_USER_KEY)
        if not pending_uid:
            return request.redirect('/web/login')

        user = request.env['res.users'].sudo().browse(pending_uid)
        masked = self._mask_email(user.email or '')

        try:
            token = request.env['auth.otp'].sudo().generate_otp(pending_uid)
            self._send_otp_email(user, token.otp_code)
            error = False
            success = _('A new OTP has been sent to your email.')
        except Exception:
            _logger.exception('2FA: failed to resend OTP for user %s', pending_uid)
            error = _('Failed to resend OTP. Please contact your administrator.')
            success = False

        return _render_otp_page({
            'user_email': masked,
            'redirect': redirect,
            'error': error,
            'success': success,
            'request': request,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _send_otp_email(user, otp_code):
        template = request.env.ref(
            'auth_2fa_email.mail_template_otp', raise_if_not_found=False
        )
        if template:
            template.sudo().with_context(otp_code=otp_code).send_mail(
                user.id, force_send=True, raise_exception=True
            )
        else:
            request.env['mail.mail'].sudo().create({
                'subject': _('Your Login Verification Code'),
                'email_to': user.email,
                'body_html': (
                    '<p>Hello %s,</p>'
                    '<p>Your one-time login code is: <strong>%s</strong></p>'
                    '<p>This code expires in 10 minutes. Do not share it with anyone.</p>'
                ) % (user.name, otp_code),
            }).send()

    @staticmethod
    def _mask_email(email):
        if '@' not in email:
            return '***'
        local, domain = email.split('@', 1)
        return '%s***@%s' % (local[:1], domain)
