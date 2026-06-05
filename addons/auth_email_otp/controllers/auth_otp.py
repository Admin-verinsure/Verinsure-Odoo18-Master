# -*- coding: utf-8 -*-
"""
Email OTP Authentication Controller
=====================================
Implements the 2FA flow by extending Odoo's native /web/login endpoint.

Flow overview:
    POST /web/login
        ↓ (credentials valid AND 2FA enabled)
    Redirect → GET /auth/otp/verify
        ↓ (OTP submitted)
    POST /auth/otp/verify
        ↓ (OTP correct)
    Session finalised → Redirect to /odoo (or original target)

Key design decisions:
- POST /web/login NEVER calls request.render() directly.
  On any error it redirects to GET /web/login with an error code in the
  query string, letting Odoo's own Home controller render the page with a
  fully-initialised env.  This avoids the "Expected singleton: res.users()"
  crash that occurs when website.layout is rendered from an auth='none' route
  with no public user in the env.
- OTP pages use auth='public' (not auth='none') so Odoo always provides a
  valid public-user env before QWeb rendering.
- Session fixation is prevented by calling session.logout() immediately after
  credentials are verified and before any 2FA state is stored.

Session keys (otp_ prefix avoids collisions with Odoo internals):
    otp_pending_uid    : int — user id awaiting 2FA
    otp_challenge_id   : int — auth.otp.challenge record id
    otp_redirect       : str — validated post-login redirect target
    otp_db             : str — database name (multi-db guard)
"""
import logging
from urllib.parse import urlparse, urlencode

from odoo import http, SUPERUSER_ID
from odoo.http import request
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session key constants
# ---------------------------------------------------------------------------
_SESSION_UID        = 'otp_pending_uid'
_SESSION_CHALLENGE  = 'otp_challenge_id'
_SESSION_REDIRECT   = 'otp_redirect'
_SESSION_DB         = 'otp_db'

# ---------------------------------------------------------------------------
# Error codes passed as ?otp_error=<code> to GET /web/login
# Odoo's Home controller picks these up and we inject them via a small
# override of the GET handler below.
# ---------------------------------------------------------------------------
_ERR_WRONG_PASSWORD  = 'wrong_password'
_ERR_NO_EMAIL        = 'no_email'
_ERR_SEND_FAILED     = 'send_failed'

_ERROR_MESSAGES = {
    _ERR_WRONG_PASSWORD: _('Wrong login/password'),
    _ERR_NO_EMAIL: _(
        'Your account requires two-factor authentication but no email address '
        'is configured. Please contact your administrator.'
    ),
    _ERR_SEND_FAILED: _(
        'Could not send verification code. '
        'Please try again or contact your administrator.'
    ),
}

# OTP page messages
_GENERIC_OTP_ERROR   = _('Invalid or expired verification code. Please try again.')
_LOCKOUT_ERROR       = _('Too many incorrect attempts. Please log in again.')
_RESEND_COOLDOWN_MSG = _('Please wait before requesting a new code.')
_RESEND_SUCCESS_MSG  = _('A new verification code has been sent to your email.')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_redirect(url: str, default: str = '/odoo') -> str:
    """Return url only if relative or same-host, else return default."""
    if not url:
        return default
    parsed = urlparse(url)
    if not parsed.netloc:
        return url
    if parsed.netloc == urlparse(request.httprequest.host_url).netloc:
        return url
    return default


def _redirect_login_error(error_code: str, redirect=None) -> object:
    """
    Redirect to GET /web/login with an error code in the query string.

    We NEVER render web.login ourselves from a POST/auth='none' route because
    website.layout crashes with "Expected singleton: res.users()" when the env
    has no public user.  Redirecting to GET /web/login lets Odoo's own
    controller render the page with a correctly initialised env.
    """
    params = {'otp_error': error_code}
    if redirect:
        params['redirect'] = redirect
    return request.redirect('/web/login?' + urlencode(params))


def _get_challenge(env, challenge_id: int, user_id: int):
    """Return the pending challenge record or None."""
    try:
        ch = env['auth.otp.challenge'].sudo().browse(challenge_id)
        if ch.exists() and ch.user_id.id == user_id and ch.state == 'pending':
            return ch
    except Exception:
        pass
    return None


def _clear_otp_session():
    """Remove all OTP-related keys from the session."""
    for key in (_SESSION_UID, _SESSION_CHALLENGE, _SESSION_REDIRECT, _SESSION_DB):
        request.session.pop(key, None)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AuthOtpController(http.Controller):

    # -----------------------------------------------------------------------
    # GET /web/login  — inject error message from query string if present
    # -----------------------------------------------------------------------

    @http.route('/web/login', type='http', auth='public', methods=['GET'],
                csrf=False, website=True)
    def web_login_get(self, otp_error=None, redirect=None, **kwargs):
        """
        Render the login page.  If ?otp_error=<code> is present (set by our
        POST handler redirect) translate it to a human-readable message and
        pass it to the template as 'login_error'.

        For all other cases we fall through to Odoo's built-in GET handler —
        we only intercept when our error code is present.
        """
        if not otp_error or otp_error not in _ERROR_MESSAGES:
            # No OTP error — let Odoo's native GET handler take over
            # by calling super via the original Home controller logic.
            # We achieve this by rendering the template directly since
            # Odoo's Home.web_login is not easily callable as super here.
            return request.render('web.login', {
                'redirect': redirect or '/odoo',
            })

        return request.render('web.login', {
            'login_error': _ERROR_MESSAGES[otp_error],
            'redirect':    redirect or '/odoo',
        })

    # -----------------------------------------------------------------------
    # POST /web/login  — credential check + 2FA gate
    # -----------------------------------------------------------------------

    @http.route('/web/login', type='http', auth='none', methods=['POST'],
                csrf=True, website=True)
    def web_login_post(self, redirect=None, **post):
        """
        Intercept login POST.

        IMPORTANT: This method NEVER calls request.render().
        All error paths redirect to GET /web/login with ?otp_error=<code>.
        This sidesteps the website.layout / res.users() singleton crash that
        occurs when rendering QWeb templates from auth='none' routes.
        """
        db       = request.db
        login    = post.get('login', '').strip()
        password = post.get('password', '')

        # --- Authenticate credentials ---
        try:
            credential = {'login': login, 'password': password, 'type': 'password'}
            # Odoo 18: returns int uid directly. Older: returns {'uid': int}.
            result = request.session.authenticate(db, credential)
            uid = result.get('uid') if isinstance(result, dict) else result
        except Exception:
            return _redirect_login_error(_ERR_WRONG_PASSWORD, redirect=redirect)

        if not uid or not isinstance(uid, int):
            return _redirect_login_error(_ERR_WRONG_PASSWORD, redirect=redirect)

        # --- Check 2FA requirement ---
        env  = request.env(user=SUPERUSER_ID)
        user = env['res.users'].browse(uid)

        if not user.email_otp_enabled:
            # No 2FA — session already authenticated, just redirect
            return request.redirect(
                _safe_redirect(redirect or request.params.get('redirect') or '/odoo')
            )

        # --- Guard: email required for 2FA ---
        if not user.email:
            _logger.error(
                'auth.otp: User %s (id=%d) has 2FA enabled but no email — blocking.',
                user.login, uid,
            )
            request.session.logout(keep_db=True)
            return _redirect_login_error(_ERR_NO_EMAIL, redirect=redirect)

        # --- Wipe session (session-fixation prevention) ---
        request.session.logout(keep_db=True)

        # --- Collect audit metadata ---
        ip_address = request.httprequest.environ.get(
            'HTTP_X_FORWARDED_FOR',
            request.httprequest.environ.get('REMOTE_ADDR', ''),
        )
        ip_address = ip_address.split(',')[0].strip()
        user_agent = (
            request.httprequest.user_agent.string
            if request.httprequest.user_agent else ''
        )

        # --- Create challenge ---
        challenge, plain_otp = env['auth.otp.challenge'].create_challenge(
            user, ip_address=ip_address, user_agent=user_agent,
        )

        # --- Send OTP email ---
        try:
            self._send_otp_email(env, user, plain_otp)
        except Exception as e:
            _logger.exception(
                'auth.otp: Failed to send OTP email to user %s (id=%d): %s',
                user.login, uid, str(e),
            )
            challenge.sudo().write({'state': 'cancelled'})
            return _redirect_login_error(_ERR_SEND_FAILED, redirect=redirect)

        # --- Store pending state ---
        request.session[_SESSION_UID]       = uid
        request.session[_SESSION_CHALLENGE] = challenge.id
        request.session[_SESSION_REDIRECT]  = _safe_redirect(
            redirect or request.params.get('redirect') or '/odoo'
        )
        request.session[_SESSION_DB]        = db
        request.session.modified            = True

        _logger.info(
            'auth.otp: 2FA challenge created for user %s (id=%d) | challenge_id=%d',
            user.login, uid, challenge.id,
        )
        return request.redirect('/auth/otp/verify')

    # -----------------------------------------------------------------------
    # Shared helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _send_otp_email(env, user, plain_otp: str):
        """Send OTP via the module mail template."""
        template = env.ref(
            'auth_email_otp.email_template_otp_code',
            raise_if_not_found=True,
        )
        template.sudo().with_context(otp_code=plain_otp).send_mail(
            user.id,
            force_send=True,
            email_values={'email_to': user.email},
        )

    # -----------------------------------------------------------------------
    # GET /auth/otp/verify  — show OTP entry form
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/verify', type='http', auth='public', methods=['GET'],
                csrf=False, website=True)
    def otp_verify_get(self, **kwargs):
        """
        Render the OTP form.

        Uses auth='public' (not auth='none') so Odoo provides a valid
        public-user env before QWeb runs — website.layout works correctly.
        """
        uid          = request.session.get(_SESSION_UID)
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        db           = request.session.get(_SESSION_DB)

        if not uid or not challenge_id or db != request.db:
            _logger.warning('auth.otp: GET /auth/otp/verify — invalid session state.')
            return request.redirect('/web/login')

        env       = request.env(user=SUPERUSER_ID)
        challenge = _get_challenge(env, challenge_id, uid)

        if not challenge:
            _logger.warning(
                'auth.otp: No valid challenge uid=%d challenge_id=%d — back to login.',
                uid, challenge_id,
            )
            _clear_otp_session()
            return request.redirect('/web/login')

        return request.render('auth_email_otp.otp_verify_page', {
            'resend_cooldown': challenge.resend_seconds_remaining(),
        })

    # -----------------------------------------------------------------------
    # POST /auth/otp/verify  — validate submitted OTP
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/verify', type='http', auth='public', methods=['POST'],
                csrf=True, website=True)
    def otp_verify_post(self, otp_code='', **kwargs):
        """
        Validate OTP and finalise session on success.
        Uses auth='public' so website.layout renders without crashing.
        """
        uid          = request.session.get(_SESSION_UID)
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        redirect_url = request.session.get(_SESSION_REDIRECT, '/odoo')
        db           = request.session.get(_SESSION_DB)

        if not uid or not challenge_id or db != request.db:
            return request.redirect('/web/login')

        env       = request.env(user=SUPERUSER_ID)
        challenge = _get_challenge(env, challenge_id, uid)

        if not challenge:
            _clear_otp_session()
            return request.redirect('/web/login')

        # Fast-reject non-6-digit input
        otp_code = (otp_code or '').strip()
        if len(otp_code) != 6 or not otp_code.isdigit():
            return request.render('auth_email_otp.otp_verify_page', {
                'error':           _GENERIC_OTP_ERROR,
                'resend_cooldown': challenge.resend_seconds_remaining(),
            })

        is_valid = challenge.verify_otp(otp_code)

        if not is_valid:
            challenge = env['auth.otp.challenge'].sudo().browse(challenge_id)
            if challenge.state == 'cancelled':
                _clear_otp_session()
                _logger.warning(
                    'auth.otp: Challenge %d uid=%d cancelled — forcing re-login.',
                    challenge_id, uid,
                )
                return request.render('web.login', {'login_error': _LOCKOUT_ERROR})

            return request.render('auth_email_otp.otp_verify_page', {
                'error':           _GENERIC_OTP_ERROR,
                'resend_cooldown': challenge.resend_seconds_remaining(),
            })

        # --- OTP correct: build authenticated session ---
        _clear_otp_session()
        user = env['res.users'].browse(uid)

        # Odoo 18: session.db must be set before uid/login or the session
        # middleware invalidates the session on the very next request.
        request.session.db            = db
        request.session.uid           = uid
        request.session.login         = user.login
        request.session.session_token = user._compute_session_token(
            request.session.sid
        )
        request.update_env(user=uid)

        _logger.info(
            'auth.otp: 2FA login complete for user %s (id=%d).', user.login, uid,
        )
        return request.redirect(_safe_redirect(redirect_url))

    # -----------------------------------------------------------------------
    # POST /auth/otp/resend
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/resend', type='http', auth='public', methods=['POST'],
                csrf=True, website=True)
    def otp_resend(self, **kwargs):
        """Resend OTP (60-second cooldown enforced by the model)."""
        uid          = request.session.get(_SESSION_UID)
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        db           = request.session.get(_SESSION_DB)

        if not uid or not challenge_id or db != request.db:
            return request.redirect('/web/login')

        env           = request.env(user=SUPERUSER_ID)
        old_challenge = _get_challenge(env, challenge_id, uid)

        if not old_challenge:
            _clear_otp_session()
            return request.redirect('/web/login')

        if not old_challenge.can_resend():
            return request.render('auth_email_otp.otp_verify_page', {
                'error':           _RESEND_COOLDOWN_MSG,
                'resend_cooldown': old_challenge.resend_seconds_remaining(),
            })

        user       = env['res.users'].browse(uid)
        ip_address = request.httprequest.environ.get(
            'HTTP_X_FORWARDED_FOR',
            request.httprequest.environ.get('REMOTE_ADDR', ''),
        )
        ip_address = ip_address.split(',')[0].strip()
        user_agent = (
            request.httprequest.user_agent.string
            if request.httprequest.user_agent else ''
        )

        new_challenge, plain_otp = env['auth.otp.challenge'].create_challenge(
            user, ip_address=ip_address, user_agent=user_agent,
        )

        try:
            self._send_otp_email(env, user, plain_otp)
        except Exception as e:
            _logger.exception(
                'auth.otp: Resend failed for user %s: %s', user.login, str(e),
            )
            new_challenge.sudo().write({'state': 'cancelled'})
            _clear_otp_session()
            return request.redirect('/web/login')

        request.session[_SESSION_CHALLENGE] = new_challenge.id
        request.session.modified            = True

        _logger.info(
            'auth.otp: OTP resent for user %s (id=%d) | new_challenge_id=%d',
            user.login, uid, new_challenge.id,
        )
        return request.render('auth_email_otp.otp_verify_page', {
            'success':         _RESEND_SUCCESS_MSG,
            'resend_cooldown': 60,
        })

    # -----------------------------------------------------------------------
    # GET|POST /auth/otp/cancel
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/cancel', type='http', auth='public',
                methods=['GET', 'POST'], csrf=False, website=True)
    def otp_cancel(self, **kwargs):
        """Abandon 2FA flow and return to login page."""
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        uid          = request.session.get(_SESSION_UID)

        if challenge_id and uid:
            try:
                env = request.env(user=SUPERUSER_ID)
                ch  = _get_challenge(env, challenge_id, uid)
                if ch:
                    ch.sudo().write({'state': 'cancelled'})
            except Exception:
                pass

        _clear_otp_session()
        return request.redirect('/web/login')