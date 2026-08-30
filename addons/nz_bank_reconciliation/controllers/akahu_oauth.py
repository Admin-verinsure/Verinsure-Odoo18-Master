# -*- coding: utf-8 -*-
import logging
import secrets
from html import escape

from odoo import fields, http, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from werkzeug.utils import redirect

from ..models.akahu_credential import OAUTH_CALLBACK_PATH, _redact_secret


_logger = logging.getLogger(__name__)

OAUTH_STATE_SESSION_KEY = 'nz_bank_reconciliation.akahu_oauth_state'
OAUTH_STATE_TTL_SECONDS = 900


def _generate_oauth_state():
    return secrets.token_urlsafe(32)

def _format_account_label(item):
    parts = [
        item.get('connection', {}).get('name') or '',
        item.get('name') or '',
        item.get('formatted_account') or '',
    ]
    label = ' - '.join(part for part in parts if part) or _('Akahu Account')
    account_id = item.get('_id') or ''
    return '%s [%s]' % (label, account_id) if account_id else label


def _user_has_company_access(user, company_id):
    return bool(user and company_id and company_id in user.company_ids.ids)


class AkahuOAuthController(http.Controller):

    @http.route('/nz_bank_reconciliation/akahu/oauth/start/<int:credential_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def akahu_oauth_start(self, credential_id, **kwargs):
        flow_kind = kwargs.get('flow_kind') or 'connect'
        credential = request.env['akahu.credential'].sudo().browse(credential_id).exists()
        try:
            if not credential:
                raise UserError(_('Akahu credential not found.'))
            if not request.env.user.has_group('base.group_erp_manager'):
                raise AccessError(_('Connecting Akahu is restricted to ERP Managers.'))
            if request.session.uid != request.env.uid:
                raise AccessError(_('Your session is not valid for Akahu OAuth.'))
            if not _user_has_company_access(request.env.user, credential.company_id.id):
                raise AccessError(_('You do not have access to this company credential.'))

            redirect_uri = credential._get_oauth_redirect_uri()
            state = _generate_oauth_state()
            request.session[OAUTH_STATE_SESSION_KEY] = {
                'state': state,
                'credential_id': credential.id,
                'company_id': credential.company_id.id,
                'user_id': request.env.uid,
                'redirect_uri': redirect_uri,
                'flow_kind': flow_kind,
                'created_at': fields.Datetime.to_string(fields.Datetime.now()),
            }

            auth_url = credential._build_oauth_authorization_url(state, redirect_uri=redirect_uri)
            _logger.info(
                'Akahu OAuth start for credential_id=%s company_id=%s flow_kind=%s redirect_uri=%s callback_path=%s authorization_url=%s',
                credential.id,
                credential.company_id.id,
                flow_kind,
                redirect_uri,
                OAUTH_CALLBACK_PATH,
                auth_url,
            )
            return redirect(auth_url)
        except (AccessError, UserError, ValidationError) as exc:
            safe_message = _redact_secret(str(exc)[:256])
            _logger.warning(
                'Akahu OAuth start rejected for credential_id=%s company_id=%s flow_kind=%s: %s',
                credential.id if credential else False,
                credential.company_id.id if credential else False,
                flow_kind,
                safe_message,
            )
            return self._render_message(
                _('Akahu OAuth failed'),
                safe_message or _('Akahu rejected the authorization request. Please verify the configured Redirect URI and Akahu application settings.'),
            )

    @http.route('/nz_bank_reconciliation/oauth/api_redirect', type='http', auth='public', methods=['GET'], csrf=False)
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
            _logger.warning(
                'Akahu OAuth callback returned error for credential_id=%s company_id=%s flow_kind=%s error=%s detail=%s',
                credential.id,
                credential.company_id.id,
                session_state.get('flow_kind') or 'connect',
                error,
                _redact_secret((error_description or '')[:256]),
            )
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
            _logger.warning(
                'Akahu OAuth callback failed for credential_id=%s company_id=%s flow_kind=%s: %s',
                credential.id,
                credential.company_id.id,
                session_state.get('flow_kind') or 'connect',
                safe_exc,
            )
            credential.sudo().write({
                'connection_status': 'error',
                'last_tested': fields.Datetime.now(),
                'error_message': safe_exc,
            })
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            return self._render_message(_('Akahu OAuth failed'), _('Akahu OAuth completed but the token exchange or account retrieval failed.'))

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
                'akahu_status': item.get('status') or 'UNKNOWN',
            }))
        if not option_values:
            request.session.pop(OAUTH_STATE_SESSION_KEY, None)
            return self._render_message(_('Akahu OAuth failed'), _('Akahu did not return any connected accounts for this token.'))

        account_model = request.env['akahu.account'].sudo()
        if len(option_values) == 1:
            selected_payload = option_values[0][2]
            existing_mappings = account_model.search([
                ('credential_id', '=', credential.id),
                ('company_id', '=', credential.company_id.id),
                ('akahu_account_id', '=', selected_payload.get('akahu_account_id')),
            ], limit=2)
            if len(existing_mappings) == 1:
                existing_mapping = existing_mappings[0]
                existing_mapping.write({
                    'bank_name': selected_payload.get('bank_name') or existing_mapping.bank_name,
                    'akahu_account_name': selected_payload.get('account_name') or existing_mapping.akahu_account_name,
                    'akahu_formatted_account': selected_payload.get('formatted_account') or existing_mapping.akahu_formatted_account,
                    'akahu_status': selected_payload.get('akahu_status') or existing_mapping.akahu_status,
                })
                request.session.pop(OAUTH_STATE_SESSION_KEY, None)
                _logger.info(
                    'Akahu OAuth callback reused existing mapping credential_id=%s company_id=%s account_id=%s mapping_id=%s',
                    credential.id,
                    credential.company_id.id,
                    selected_payload.get('akahu_account_id'),
                    existing_mapping.id,
                )
                return redirect('/web#id=%s&model=akahu.account&view_type=form' % existing_mapping.id)

        wizard = request.env['akahu.oauth.account.select.wizard'].sudo().create({
            'credential_id': credential.id,
            'option_ids': option_values,
        })
        if len(option_values) == 1 and wizard.option_ids:
            wizard.write({'selected_option_id': wizard.option_ids[0].id})

        request.session.pop(OAUTH_STATE_SESSION_KEY, None)
        _logger.info(
            'Akahu OAuth callback succeeded for credential_id=%s company_id=%s flow_kind=%s accounts_returned=%s wizard_id=%s',
            credential.id,
            credential.company_id.id,
            session_state.get('flow_kind') or 'connect',
            len(option_values),
            wizard.id,
        )
        return redirect('/web#id=%s&model=akahu.oauth.account.select.wizard&view_type=form' % wizard.id)

    def _render_message(self, title, message):
        body = '<html><body><h3>%s</h3><p>%s</p><p><a href="/web">Return to Odoo</a></p></body></html>' % (
            escape(title or ''),
            escape(message or ''),
        )
        return request.make_response(body, headers=[('Content-Type', 'text/html; charset=utf-8')])
