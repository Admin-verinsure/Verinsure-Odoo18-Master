# -*- coding: utf-8 -*-
import logging
from odoo import http, _
from odoo.http import request
from odoo.addons.web.controllers.home import Home

_logger = logging.getLogger(__name__)

# Session key used to carry the pending user id between the two login steps
_PENDING_2FA_USER_KEY = '2fa_pending_user_id'


class TwoFactorAuthController(Home):
    """
    Overrides Odoo 18's standard /web/login endpoint to inject an OTP step
    when the authenticating user has two_factor_enabled = True.

    Flow:
      1. User submits login + password  →  standard credential check runs.
      2. If 2FA is ON for that user:
         - uid is stored in session (but NOT committed as authenticated)
         - OTP is generated & emailed
         - User is redirected to /web/login/otp
      3. User submits the 6-digit code  →  code is verified
         - Success: session is finalised, user redirected to /odoo or /web
         - Failure: error shown on OTP page
    """

    # ------------------------------------------------------------------
    # Step 1 – intercept the normal login POST
    # ------------------------------------------------------------------
    @http.route('/web/login', type='http', auth='none', methods=['GET', 'POST'], sitemap=False)
    def web_login(self, redirect=None, **kw):
        # Let the parent handle GET and any non-2FA POST normally
        response = super().web_login(redirect=redirect, **kw)

        if request.httprequest.method != 'POST':
            return response

        # After a successful credential check, Odoo sets request.session.uid
        uid = request.session.uid
        if not uid:
            # Bad credentials – parent already returned the error page
            return response

        user = request.env['res.users'].sudo().browse(uid)
        if not user.two_factor_enabled:
            # 2FA not required for this user – proceed normally
            return response

        # ---- 2FA required: park the uid and send OTP ----
        # Remove the fully-authenticated session so the user cannot access
        # Odoo without completing the second factor.
        request.session[_PENDING_2FA_USER_KEY] = uid
        request.session.uid = None          # un-authenticate the session
        request.session.login = None
        request.session.password = ''

        # Generate & send OTP
        try:
            token = request.env['auth.otp'].sudo().generate_otp(uid)
            self._send_otp_email(user, token.otp_code)
        except Exception:
            _logger.exception('2FA: failed to send OTP email to user %s', uid)
            return request.render('auth_2fa_email.otp_page', {
                'error': _('Could not send OTP email. Please contact your administrator.'),
                'redirect': redirect or '/odoo',
            })

        return request.redirect('/web/login/otp?redirect=%s' % (redirect or '/odoo'))

    # ------------------------------------------------------------------
    # Step 2 – OTP verification page
    # ------------------------------------------------------------------
    @http.route('/web/login/otp', type='http', auth='none', methods=['GET', 'POST'], sitemap=False)
    def otp_verify(self, redirect='/odoo', **kw):
        pending_uid = request.session.get(_PENDING_2FA_USER_KEY)

        if not pending_uid:
            # No pending login – send them back to login
            return request.redirect('/web/login')

        if request.httprequest.method == 'GET':
            user = request.env['res.users'].sudo().browse(pending_uid)
            return request.render('auth_2fa_email.otp_page', {
                'user_email': self._mask_email(user.email or ''),
                'redirect': redirect,
                'error': None,
            })

        # POST – verify submitted code
        code = (kw.get('otp_code') or '').strip()
        valid = request.env['auth.otp'].sudo().verify_otp(pending_uid, code)

        if not valid:
            user = request.env['res.users'].sudo().browse(pending_uid)
            return request.render('auth_2fa_email.otp_page', {
                'user_email': self._mask_email(user.email or ''),
                'redirect': redirect,
                'error': _('Invalid or expired OTP. Please try again.'),
            })

        # OTP valid – finalise the session
        request.session.pop(_PENDING_2FA_USER_KEY, None)
        user = request.env['res.users'].sudo().browse(pending_uid)

        # Replicate what Odoo does internally after a successful login
        request.session.uid = pending_uid
        request.session.login = user.login
        request.session.session_token = user._compute_session_token(request.session.sid)

        return request.redirect(redirect)

    # ------------------------------------------------------------------
    # Resend OTP (AJAX / redirect)
    # ------------------------------------------------------------------
    @http.route('/web/login/otp/resend', type='http', auth='none', methods=['GET'], sitemap=False)
    def otp_resend(self, redirect='/odoo', **kw):
        pending_uid = request.session.get(_PENDING_2FA_USER_KEY)
        if not pending_uid:
            return request.redirect('/web/login')

        user = request.env['res.users'].sudo().browse(pending_uid)
        try:
            token = request.env['auth.otp'].sudo().generate_otp(pending_uid)
            self._send_otp_email(user, token.otp_code)
            msg = _('A new OTP has been sent to your email.')
            error = None
        except Exception:
            _logger.exception('2FA: failed to resend OTP for user %s', pending_uid)
            msg = None
            error = _('Failed to resend OTP. Please contact your administrator.')

        return request.render('auth_2fa_email.otp_page', {
            'user_email': self._mask_email(user.email or ''),
            'redirect': redirect,
            'error': error,
            'success': msg,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _send_otp_email(user, otp_code):
        """Send the OTP code to the user via Odoo's mail system."""
        template = request.env.ref(
            'auth_2fa_email.mail_template_otp', raise_if_not_found=False
        )
        if template:
            template.sudo().with_context(otp_code=otp_code).send_mail(
                user.id, force_send=True, raise_exception=True
            )
        else:
            # Fallback: send a plain email
            request.env['mail.mail'].sudo().create({
                'subject': _('Your Login Verification Code'),
                'email_to': user.email,
                'body_html': _(
                    '<p>Hello %(name)s,</p>'
                    '<p>Your one-time login code is: <strong>%(code)s</strong></p>'
                    '<p>This code expires in 10 minutes. Do not share it with anyone.</p>',
                    name=user.name, code=otp_code
                ),
            }).send()

    @staticmethod
    def _mask_email(email):
        """Return a partially masked email for display, e.g. j***@example.com"""
        if '@' not in email:
            return '***'
        local, domain = email.split('@', 1)
        visible = local[:1] if local else ''
        return '%s***@%s' % (visible, domain)
