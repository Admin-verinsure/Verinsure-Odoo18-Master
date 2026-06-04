# -*- coding: utf-8 -*-
import logging
from odoo import http, _
from odoo.http import request, Response
from odoo.addons.web.controllers.home import Home

_logger = logging.getLogger(__name__)

_PENDING_2FA_USER_KEY = '2fa_pending_user_id'


def _render_otp_page(values):
    """
    Render using ir.ui.view directly with sudo() so website.layout
    pipeline is never triggered, even with the website module installed.
    """
    html = request.env['ir.ui.view'].sudo()._render_template(
        'auth_2fa_email.otp_page', values
    )
    return Response(html, content_type='text/html;charset=utf-8', status=200)


class TwoFactorAuthController(Home):

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

        # Park uid, strip the authenticated session
        request.session[_PENDING_2FA_USER_KEY] = uid
        request.session.uid = None
        request.session.login = None
        request.session.password = ''
        request.session.session_token = None

        try:
            token = request.env['auth.otp'].sudo().generate_otp(uid)
            self._send_otp_email(user, token.otp_code)
            _logger.info('2FA: OTP sent successfully to user %s (%s)', uid, user.email)
        except Exception as e:
            _logger.exception('2FA: failed to send OTP email to user %s: %s', uid, str(e))
            return _render_otp_page({
                'user_email': self._mask_email(user.email or ''),
                'redirect': redirect or '/odoo',
                'error': _('Could not send OTP email: %s. Please contact your administrator.') % str(e),
                'success': False,
                'request': request,
            })

        return request.redirect('/web/login/otp?redirect=%s' % (redirect or '/odoo'))

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

        # Finalise session
        request.session.pop(_PENDING_2FA_USER_KEY, None)
        request.session.uid = pending_uid
        request.session.login = user.login
        request.session.session_token = user._compute_session_token(request.session.sid)
        return request.redirect(redirect)

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
        except Exception as e:
            _logger.exception('2FA resend failed: %s', str(e))
            error = _('Failed to resend OTP: %s') % str(e)
            success = False

        return _render_otp_page({
            'user_email': masked,
            'redirect': redirect,
            'error': error,
            'success': success,
            'request': request,
        })

    @staticmethod
    def _send_otp_email(user, otp_code):
        """Send OTP via plain mail.mail — avoids template rendering issues."""
        mail = request.env['mail.mail'].sudo().create({
            'subject': 'Your Login Verification Code - %s' % otp_code,
            'email_to': user.email,
            'email_from': request.env['ir.mail_server'].sudo().search([], limit=1).smtp_user
                          or request.env['ir.config_parameter'].sudo().get_param('web.base.url'),
            'body_html': '''
<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:20px;">
  <div style="background:#714B67;padding:20px;border-radius:8px 8px 0 0;text-align:center;">
    <h2 style="color:#fff;margin:0;font-size:18px;">Login Verification Code</h2>
  </div>
  <div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;border-radius:0 0 8px 8px;">
    <p style="color:#333;font-size:15px;">Hello <strong>%s</strong>,</p>
    <p style="color:#555;font-size:14px;">Use the code below to complete your login:</p>
    <div style="background:#fff;border:2px dashed #714B67;border-radius:8px;padding:20px;text-align:center;margin:20px 0;">
      <div style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:2px;margin-bottom:8px;">One-Time Password</div>
      <div style="font-size:38px;font-weight:bold;letter-spacing:10px;color:#714B67;font-family:'Courier New',monospace;">%s</div>
    </div>
    <p style="color:#999;font-size:12px;">This code expires in <strong>10 minutes</strong>. Never share it with anyone.</p>
  </div>
</div>
''' % (user.name, otp_code),
            'auto_delete': True,
        })
        mail.send(raise_exception=True)

    @staticmethod
    def _mask_email(email):
        if '@' not in email:
            return '***'
        local, domain = email.split('@', 1)
        return '%s***@%s' % (local[:1], domain)
