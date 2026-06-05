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

Security architecture:
- Pending auth state is stored in the Werkzeug session cookie (signed/encrypted).
- Session is wiped after credentials check and before 2FA completes
  (session fixation prevention).
- CSRF validated on every POST via Odoo built-in (csrf=True).
- Redirect target validated against current host (open-redirect prevention).
- Generic error messages only — no user-existence information leaked.

Session keys (otp_ prefix avoids collisions):
    otp_pending_uid    : int — user id awaiting 2FA
    otp_challenge_id   : int — auth.otp.challenge record id
    otp_redirect       : str — post-login redirect target
    otp_db             : str — database name (multi-db safety)
"""
import logging
from urllib.parse import urlparse

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
# User-facing messages  (keep generic — never leak internals)
# ---------------------------------------------------------------------------
_GENERIC_ERROR       = _('Invalid or expired verification code. Please try again.')
_LOCKOUT_ERROR       = _('Too many incorrect attempts. Please log in again.')
_RESEND_COOLDOWN_MSG = _('Please wait before requesting a new code.')
_RESEND_SUCCESS_MSG  = _('A new verification code has been sent to your email.')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_redirect(url: str, default: str = '/odoo') -> str:
    """Return url only if it is relative or on the same host — else default."""
    if not url:
        return default
    parsed = urlparse(url)
    if not parsed.netloc:          # relative path — always safe
        return url
    request_host = urlparse(request.httprequest.host_url).netloc
    if parsed.netloc == request_host:
        return url
    return default


def _get_challenge(env, challenge_id: int, user_id: int):
    """
    Return the auth.otp.challenge record if it exists, belongs to user_id,
    and is still in 'pending' state.  Returns None otherwise.
    """
    try:
        challenge = env['auth.otp.challenge'].sudo().browse(challenge_id)
        if (
            challenge.exists()
            and challenge.user_id.id == user_id
            and challenge.state == 'pending'
        ):
            return challenge
    except Exception:
        pass
    return None


def _clear_otp_session():
    """Remove every OTP-related key from the current session."""
    for key in (_SESSION_UID, _SESSION_CHALLENGE, _SESSION_REDIRECT, _SESSION_DB):
        request.session.pop(key, None)


def _ensure_public_user():
    """
    Ensure the request environment has at least the public user set.

    This is required before calling request.render() with website=True
    templates (e.g. web.login, website.layout) from auth='none' routes.
    Without it Odoo's website.layout QWeb evaluates website.add_to_cart_action
    against an empty res.users() recordset and raises:
        ValueError: Expected singleton: res.users()
    """
    if not request.env.uid:
        request.env['ir.http']._auth_method_public()


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AuthOtpController(http.Controller):
    """
    Intercepts POST /web/login to inject 2FA, then handles the OTP
    verification sub-flow at /auth/otp/verify.
    """

    # -----------------------------------------------------------------------
    # POST /web/login  — credential check + 2FA gate
    # -----------------------------------------------------------------------

    @http.route('/web/login', type='http', auth='none', methods=['POST'],
                csrf=True, website=True)
    def web_login_post(self, redirect=None, **post):
        """
        Override POST /web/login to inject 2FA.

        1. Authenticate credentials via session.authenticate().
        2. No 2FA  → session already authenticated, redirect normally.
        3. 2FA on  → wipe session, create challenge, redirect to /auth/otp/verify.

        Odoo 18 note: session.authenticate() returns the uid (int) directly,
        NOT a dict like older versions.  We handle both shapes defensively.

        website.layout note: request.render() on an auth='none' route needs a
        valid env user or website.layout raises "Expected singleton: res.users()".
        We call _ensure_public_user() before every render() call.
        """
        # Ensure public env is ready for template rendering
        _ensure_public_user()

        db       = request.db
        login    = post.get('login', '').strip()
        password = post.get('password', '')

        # --- Step 1: Attempt native Odoo authentication ---
        try:
            credential = {
                'login':    login,
                'password': password,
                'type':     'password',
            }
            # Odoo 18 returns int uid; older builds returned {'uid': int}.
            result = request.session.authenticate(db, credential)
            uid = result.get('uid') if isinstance(result, dict) else result
        except Exception:
            return self._render_login_error(_('Wrong login/password'), redirect=redirect)

        if not uid or not isinstance(uid, int):
            return self._render_login_error(_('Wrong login/password'), redirect=redirect)

        # --- Step 2: Check whether this user requires 2FA ---
        env  = request.env(user=SUPERUSER_ID)
        user = env['res.users'].browse(uid)

        if not user.email_otp_enabled:
            # 2FA not required — session is already authenticated, just redirect
            return request.redirect(
                _safe_redirect(redirect or request.params.get('redirect') or '/odoo')
            )

        # --- Step 3: Guard — user must have an email address ---
        if not user.email:
            _logger.error(
                'auth.otp: User %s (id=%d) has 2FA enabled but no email — blocking login.',
                user.login, uid,
            )
            request.session.logout(keep_db=True)
            _ensure_public_user()
            return self._render_login_error(
                _(
                    'Your account requires two-factor authentication but no email '
                    'address is configured. Please contact your administrator.'
                ),
                redirect=redirect,
            )

        # --- Step 4: Wipe the authenticated session (session-fixation prevention) ---
        # User is NOT logged in yet — we start a fresh anonymous session.
        request.session.logout(keep_db=True)
        _ensure_public_user()

        # --- Step 5: Gather audit metadata ---
        ip_address = request.httprequest.environ.get(
            'HTTP_X_FORWARDED_FOR',
            request.httprequest.environ.get('REMOTE_ADDR', ''),
        )
        ip_address = ip_address.split(',')[0].strip()
        user_agent = (
            request.httprequest.user_agent.string
            if request.httprequest.user_agent else ''
        )

        # --- Step 6: Create OTP challenge record ---
        challenge, plain_otp = env['auth.otp.challenge'].create_challenge(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # --- Step 7: Send OTP email ---
        try:
            self._send_otp_email(env, user, plain_otp)
        except Exception as e:
            _logger.exception(
                'auth.otp: Failed to send OTP email to user %s (id=%d): %s',
                user.login, uid, str(e),
            )
            challenge.sudo().write({'state': 'cancelled'})
            return self._render_login_error(
                _(
                    'Could not send verification code. '
                    'Please try again or contact your administrator.'
                ),
                redirect=redirect,
            )

        # --- Step 8: Store pending state in session ---
        request.session[_SESSION_UID]       = uid
        request.session[_SESSION_CHALLENGE] = challenge.id
        request.session[_SESSION_REDIRECT]  = _safe_redirect(
            redirect or request.params.get('redirect') or '/odoo'
        )
        request.session[_SESSION_DB]        = db
        request.session.modified            = True

        _logger.info(
            'auth.otp: 2FA challenge initiated for user %s (id=%d) | challenge_id=%d',
            user.login, uid, challenge.id,
        )
        return request.redirect('/auth/otp/verify')

    # -----------------------------------------------------------------------
    # Shared render helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _render_login_error(message: str, redirect=None):
        """
        Render the standard Odoo login page with an error banner.

        Odoo 18 note: the web.login QWeb template expects the key 'login_error',
        NOT 'error'.  Passing 'error' silently renders a blank error area.
        """
        _ensure_public_user()
        return request.render('web.login', {
            'login_error': message,
            'redirect':    redirect,
        })

    @staticmethod
    def _send_otp_email(env, user, plain_otp: str):
        """Dispatch the OTP code via the module's mail template."""
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
    # GET /auth/otp/verify  — show the OTP entry form
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/verify', type='http', auth='none', methods=['GET'],
                csrf=False, website=True)
    def otp_verify_get(self, **kwargs):
        """
        Display the OTP verification form after validating session state.

        Odoo 18 note: do NOT call _auth_method_public() before reading session
        keys — it reinitialises the env and can wipe session-local state on
        some Odoo builds.  Call _ensure_public_user() only when about to render.
        """
        uid          = request.session.get(_SESSION_UID)
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        db           = request.session.get(_SESSION_DB)

        if not uid or not challenge_id or db != request.db:
            _logger.warning(
                'auth.otp: GET /auth/otp/verify — missing or invalid session state.'
            )
            return request.redirect('/web/login')

        env       = request.env(user=SUPERUSER_ID)
        challenge = _get_challenge(env, challenge_id, uid)

        if not challenge:
            _logger.warning(
                'auth.otp: No valid pending challenge for uid=%d challenge_id=%d'
                ' — redirecting to login.',
                uid, challenge_id,
            )
            _clear_otp_session()
            return request.redirect('/web/login')

        _ensure_public_user()
        return request.render('auth_email_otp.otp_verify_page', {
            'resend_cooldown': challenge.resend_seconds_remaining(),
        })

    # -----------------------------------------------------------------------
    # POST /auth/otp/verify  — validate submitted OTP code
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/verify', type='http', auth='none', methods=['POST'],
                csrf=True, website=True)
    def otp_verify_post(self, otp_code='', **kwargs):
        """
        Validate the submitted OTP and finalise the session on success.

        Security controls:
        - Session state (uid / challenge_id / db) validated first.
        - Input rejected early if not exactly 6 digits.
        - Hash comparison is constant-time inside challenge.verify_otp().
        - On success: session.db set explicitly before uid (Odoo 18 requirement).
        - On lockout: session cleared, user sent back to login.
        - All error messages are generic.
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

        # Fast-reject obviously invalid input before touching the DB
        otp_code = (otp_code or '').strip()
        if len(otp_code) != 6 or not otp_code.isdigit():
            _ensure_public_user()
            return request.render('auth_email_otp.otp_verify_page', {
                'error':          _GENERIC_ERROR,
                'resend_cooldown': challenge.resend_seconds_remaining(),
            })

        # Constant-time hash comparison delegated to the model
        is_valid = challenge.verify_otp(otp_code)

        if not is_valid:
            # Re-fetch to detect lockout / expiry state change
            challenge = env['auth.otp.challenge'].sudo().browse(challenge_id)
            if challenge.state == 'cancelled':
                _clear_otp_session()
                _logger.warning(
                    'auth.otp: Challenge %d for uid=%d cancelled (lockout/expiry)'
                    ' — forcing re-login.',
                    challenge_id, uid,
                )
                _ensure_public_user()
                return request.render('web.login', {'login_error': _LOCKOUT_ERROR})

            _ensure_public_user()
            return request.render('auth_email_otp.otp_verify_page', {
                'error':          _GENERIC_ERROR,
                'resend_cooldown': challenge.resend_seconds_remaining(),
            })

        # --- OTP correct: finalise the authenticated session ---
        _clear_otp_session()
        user = env['res.users'].browse(uid)

        # Odoo 18: session.db MUST be set before uid/login.
        # Without it the session middleware treats the session as invalid and
        # immediately logs the user out on the very next request.
        request.session.db            = db
        request.session.uid           = uid
        request.session.login         = user.login
        request.session.session_token = user._compute_session_token(
            request.session.sid
        )

        # Refresh request.env so the rest of this request sees the real user
        request.update_env(user=uid)

        _logger.info(
            'auth.otp: 2FA login complete for user %s (id=%d).',
            user.login, uid,
        )
        return request.redirect(_safe_redirect(redirect_url))

    # -----------------------------------------------------------------------
    # POST /auth/otp/resend  — issue a fresh OTP code
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/resend', type='http', auth='none', methods=['POST'],
                csrf=True, website=True)
    def otp_resend(self, **kwargs):
        """
        Cancel the current challenge and send a new OTP.
        A 60-second cooldown is enforced via challenge.can_resend().
        """
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
            remaining = old_challenge.resend_seconds_remaining()
            _ensure_public_user()
            return request.render('auth_email_otp.otp_verify_page', {
                'error':          _RESEND_COOLDOWN_MSG,
                'resend_cooldown': remaining,
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

        # create_challenge() cancels the old challenge automatically
        new_challenge, plain_otp = env['auth.otp.challenge'].create_challenge(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        try:
            self._send_otp_email(env, user, plain_otp)
        except Exception as e:
            _logger.exception(
                'auth.otp: Failed to resend OTP to user %s: %s',
                user.login, str(e),
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

        _ensure_public_user()
        return request.render('auth_email_otp.otp_verify_page', {
            'success':        _RESEND_SUCCESS_MSG,
            'resend_cooldown': 60,
        })

    # -----------------------------------------------------------------------
    # GET|POST /auth/otp/cancel  — abandon 2FA and return to login
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/cancel', type='http', auth='none',
                methods=['GET', 'POST'], csrf=False, website=True)
    def otp_cancel(self, **kwargs):
        """Cancel the OTP flow, mark the challenge as cancelled, go to login."""
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        uid          = request.session.get(_SESSION_UID)

        if challenge_id and uid:
            try:
                env       = request.env(user=SUPERUSER_ID)
                challenge = _get_challenge(env, challenge_id, uid)
                if challenge:
                    challenge.sudo().write({'state': 'cancelled'})
            except Exception:
                pass

        _clear_otp_session()
        return request.redirect('/web/login')