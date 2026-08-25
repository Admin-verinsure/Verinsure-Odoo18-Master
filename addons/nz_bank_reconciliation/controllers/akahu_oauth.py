# -*- coding: utf-8 -*-
import logging
import secrets
from urllib.parse import quote, urlparse

from odoo import fields, http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from werkzeug.utils import redirect

from ..models.akahu_credential import _redact_secret


_logger = logging.getLogger(__name__)

OAUTH_STATE_SESSION_KEY = 'nz_bank_reconciliation.akahu_oauth_state'
OAUTH_STATE_TTL_SECONDS = 900


def _generate_oauth_state():
    return secrets.token_urlsafe(32)


def _build_authorization_url(app_token, redirect_uri, state):
    return 'https://oauth.akahu.nz?response_type=code&client_id=%s&redirect_uri=%s&scope=ENDURING_CONSENT&state=%s' % (
        quote(app_token, safe=''),
        quote(redirect_uri, safe=''),
        quote(state, safe=''),
    )


def _is_https_callback(redirect_uri):
    parsed = urlparse(redirect_uri or '')
    return parsed.scheme == 'https'


def _format_account_label(item):
    parts = [
        item.get('connection', {}).get('name') or '',
        item.get('name') or '',
        item.get('formatted_account') or '',
    ]
    return ' - '.join(part for part in parts if part) or (item.get('_id') or _('Akahu Account'))


def _user_has_company_access(user, company_id):
    return bool(user and company_id and company_id in user.company_ids.ids)


class AkahuOAuthController(http.Controller):

    @http.route('/nz_bank_reconciliation/akahu/oauth/start/<int:credential_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def akahu_oauth_start(self, credential_id, **kwargs):
        credential = request.env['akahu.credential'].sudo().browse(credential_id).exists()
        if not credential:
            raise UserError(_('Akahu credential not found.'))
        if not request.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('Connecting Akahu is restricted to ERP Managers.'))
        if request.session.uid != request.env.uid:
            raise AccessError(_('Your session is not valid for Akahu OAuth.'))
        if not _user_has_company_access(request.env.user, credential.company_id.id):
            raise AccessError(_('You do not have access to this company credential.'))

        redirect_uri = credential.oauth_redirect_uri
        if not redirect_uri:
            raise UserError(_('Please configure the Akahu OAuth Redirect URI before connecting.'))
        if not _is_https_callback(redirect_uri) and not redirect_uri.startswith('http://localhost'):
            raise UserError(_('Akahu OAuth Redirect URI must use HTTPS in production.'))

        state = _generate_oauth_state()
        request.session[OAUTH_STATE_SESSION_KEY] = {
            'state': state,
            'credential_id': credential.id,
            'company_id': credential.company_id.id,
            'user_id': request.env.uid,
            'redirect_uri': redirect_uri,
            'created_at': fields.Datetime.now(),
        }

        auth_url = credential._build_oauth_authorization_url(state, redirect_uri=redirect_uri)
        return redirect(auth_url)

    @http.route('/nz_bank_reconciliation/akahu/oauth/callback', type='http', auth='public', methods=['GET'], csrf=False)
    def akahu_oauth_callback(self, **kwargs):
        session_state = request.session.get(OAUTH_STATE_SESSION_KEY) or {}
        error = kwargs.get('error')
        error_description = kwargs.get('error_description') or kwargs.get('message')
        state = kwargs.get('state')
        code = kwargs.get('code')

        if not session_state:
            return self._render_message(_('Akahu OAuth failed'), _('No pending OAuth session was found. Please try again from Odoo.'))
        if state != session_state.get('state'):
            return self._render_message(_('Akahu OAuth failed'), _('Invalid OAuth state. Please restart the connection from Odoo.'))
        if request.session.uid != session_state.get('user_id'):
            return self._render_message(_('Akahu OAuth failed'), _('Your Odoo session changed before the callback completed. Please try again.'))

        session_user = request.env['res.users'].sudo().browse(request.session.uid).exists() if request.session.uid else False
        if not session_user or session_state.get('credential_id') is None:
            return self._render_message(_('Akahu OAuth failed'), _('Your Odoo session is no longer valid. Please start again.'))
        if not _user_has_company_access(session_user, session_state.get('company_id')):
            return self._render_message(_('Akahu OAuth failed'), _('You do not have access to the company associated with this OAuth flow.'))

        created_at = session_state.get('created_at')
        try:
            created_dt = fields.Datetime.from_string(created_at) if created_at else None
        except Exception:
            created_dt = None
        now_dt = fields.Datetime.from_string(fields.Datetime.now())
        if not created_dt or (now_dt - created_dt).total_seconds() > OAUTH_STATE_TTL_SECONDS:
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            return self._render_message(_('Akahu OAuth failed'), _('The OAuth session expired. Please start again from Odoo.'))

        credential = request.env['akahu.credential'].sudo().browse(session_state.get('credential_id')).exists()
        if not credential or credential.company_id.id != session_state.get('company_id'):
            return self._render_message(_('Akahu OAuth failed'), _('The OAuth callback does not match the original company credential.'))

        if error:
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            message = error_description or error
            if error in ('access_denied', 'user_cancelled', 'cancelled'):
                message = _('Akahu authorization was cancelled or denied.')
            return self._render_message(_('Akahu OAuth cancelled'), message)

        if not code:
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            return self._render_message(_('Akahu OAuth failed'), _('Missing authorization code in the callback.'))

        try:
            user_token = credential._exchange_oauth_code(code, redirect_uri=session_state.get('redirect_uri'))
            credential.sudo().write({
                'user_access_token': user_token,
                'connection_status': 'ok',
                'last_tested': fields.Datetime.now(),
                'error_message': False,
            })
            accounts = credential._fetch_oauth_accounts(user_token)
        except Exception as exc:
            safe_exc = _redact_secret(str(exc)[:256])
            _logger.warning('Akahu OAuth callback failed for credential_id=%s: %s', credential.id, safe_exc)
            credential.sudo().write({
                'connection_status': 'error',
                'last_tested': fields.Datetime.now(),
                'error_message': safe_exc,
            })
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            return self._render_message(_('Akahu OAuth failed'), _('Akahu OAuth completed but the token exchange or account retrieval failed.'))

        wizard = request.env['akahu.oauth.account.select.wizard'].sudo().create({
            'credential_id': credential.id,
        })
        option_values = []
        for item in accounts:
            account_id = item.get('_id') or ''
            if not account_id:
                continue
            option_values.append((0, 0, {
                'akahu_account_id': account_id,
                'display_name': _format_account_label(item),
                'bank_name': item.get('connection', {}).get('name') or '',
                'account_name': item.get('name') or '',
                'formatted_account': item.get('formatted_account') or '',
            }))
        if not option_values:
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            return self._render_message(_('Akahu OAuth failed'), _('Akahu did not return any connected accounts for this token.'))

        wizard.write({'option_ids': option_values})
        first_option = wizard.option_ids[:1]
        if first_option:
            wizard.write({'selected_option_id': first_option.id})
        request.session.pop(OAUTH_STATE_SESSION_KEY, None)
        return redirect('/web#id=%s&model=akahu.oauth.account.select.wizard&view_type=form' % wizard.id)

    def _render_message(self, title, message):
        body = '<html><body><h3>%s</h3><p>%s</p><p><a href="/web">Return to Odoo</a></p></body></html>' % (title, message)
        return request.make_response(body, headers=[('Content-Type', 'text/html; charset=utf-8')])
