# -*- coding: utf-8 -*-
"""
Email OTP Authentication Controller
=====================================
Implements the 2FA flow by extending Odoo's native /web/login endpoint.

Flow overview:
    POST /web/login
        ↓ (credentials valid AND 2FA enabled)
    Redirect → GET /auth/otp/verify?next=<encoded_url>
        ↓ (OTP submitted)
    POST /auth/otp/verify
        ↓ (OTP correct)
    Session finalised → Redirect to `next`

Security architecture:
- Pending auth state is stored in an encrypted, signed Odoo session cookie
  (standard Werkzeug session) — NOT in the URL or a plain cookie.
- The session is given a new SID (session fixation prevention) only after
  the full 2FA flow completes and the user is truly authenticated.
- CSRF token is validated on every POST via Odoo's built-in mechanism
  (`type='http', csrf=True`).
- The `next` redirect is validated against the current host to prevent
  open-redirect attacks.
- No information about whether a user exists is ever exposed to the client.
- All error messages are generic.

Session keys used (prefixed to avoid collisions):
    otp_pending_uid       : int  — user id awaiting 2FA
    otp_challenge_id      : int  — auth.otp.challenge record id
    otp_redirect          : str  — post-login redirect target
    otp_db                : str  — database name (multi-db safety)
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
_SESSION_UID       = 'otp_pending_uid'
_SESSION_CHALLENGE = 'otp_challenge_id'
_SESSION_REDIRECT  = 'otp_redirect'
_SESSION_DB        = 'otp_db'

# ---------------------------------------------------------------------------
# User-facing messages  (generic — never reveal internals)
# ---------------------------------------------------------------------------
_GENERIC_ERROR      = _('Invalid or expired verification code. Please try again.')
_LOCKOUT_ERROR      = _('Too many incorrect attempts. Please log in again.')
_RESEND_COOLDOWN_MSG = _('Please wait before requesting a new code.')
_RESEND_SUCCESS_MSG  = _('A new verification code has been sent to your email.')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_redirect(url: str, default: str = '/odoo') -> str:
    """
    Validate redirect URL to prevent open-redirect attacks.
    Only allows relative URLs or URLs on the same host.
    """
    if not url:
        return default
    parsed = urlparse(url)
    # Allow relative paths (no netloc means relative)
    if not parsed.netloc:
        return url
    # Allow same host
    request_host = urlparse(request.httprequest.host_url).netloc
    if parsed.netloc == request_host:
        return url
    return default


def _get_challenge(env, challenge_id: int, user_id: int):
    """
    Fetch the auth.otp.challenge record safely.
    Returns None if not found, wrong user, or not in 'pending' state.
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
    """Remove all OTP-related keys from the session."""
    for key in (_SESSION_UID, _SESSION_CHALLENGE, _SESSION_REDIRECT, _SESSION_DB):
        request.session.pop(key, None)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AuthOtpController(http.Controller):
    """
    Intercepts /web/login POST to inject 2FA when required,
    and handles the OTP verification sub-flow at /auth/otp/verify.
    """

    # -----------------------------------------------------------------------
    # Login interception — POST /web/login
    # -----------------------------------------------------------------------

    @http.route('/web/login', type='http', auth='none', methods=['POST'], csrf=True, website=True)
    def web_login_post(self, redirect=None, **post):
        """
        Override POST /web/login to inject 2FA.

        Strategy:
        1. Call Odoo's native login logic via request.session.authenticate().
        2. If authentication fails → fall through to native error page.
        3. If user has 2FA disabled → allow native redirect to complete.
        4. If user has 2FA enabled:
           a. Clear the just-created session (prevent session fixation).
           b. Store pending state in a fresh anonymous session.
           c. Generate OTP challenge and send email.
           d. Redirect to /auth/otp/verify.

        NOTE (Odoo 18): session.authenticate() returns the uid (int) directly,
        NOT a dict. Subscripting the return value with ['uid'] raises TypeError
        and causes a 500. We handle both cases defensively below.
        """
        db    = request.db
        login = post.get('login', '').strip()
        password = post.get('password', '')

        # --- Step 1: Attempt native Odoo authentication ---
        try:
            credential = {
                'login': login,
                'password': password,
                'type': 'password',
            }
            # Odoo 18: authenticate() returns int uid on success, or raises.
            result = request.session.authenticate(db, credential)

            # Defensive: handle both int (Odoo 18) and dict (older builds)
            if isinstance(result, dict):
                uid = result.get('uid')
            else:
                uid = result

        except Exception:
            # Wrong credentials or any auth error — show login page with error
            return self._render_login_error(
                _('Wrong login/password'),
                redirect=redirect,
            )

        if not uid or not isinstance(uid, int):
            return self._render_login_error(
                _('Wrong login/password'),
                redirect=redirect,
            )

        # --- Step 2: Check if this user has 2FA enabled ---
        env  = request.env(user=SUPERUSER_ID)
        user = env['res.users'].browse(uid)

        if not user.email_otp_enabled:
            # 2FA not required — session is already authenticated, just redirect
            redirect_url = _safe_redirect(
                redirect or request.params.get('redirect') or '/odoo'
            )
            return request.redirect(redirect_url)

        # --- Step 3: 2FA required — validate email exists ---
        if not user.email:
            _logger.error(
                'auth.otp: User %s (id=%d) has 2FA enabled but no email configured'
                ' — blocking login.',
                user.login, uid,
            )
            request.session.logout(keep_db=True)
            return self._render_login_error(
                _(
                    'Your account requires two-factor authentication but no email '
                    'address is configured. Please contact your administrator.'
                ),
                redirect=redirect,
            )

        # --- Step 4: Wipe the authenticated session (prevent session fixation) ---
        # The user is NOT considered logged in yet — start a fresh anonymous session.
        request.session.logout(keep_db=True)

        # --- Step 5: Collect request metadata for audit trail ---
        ip_address = request.httprequest.environ.get(
            'HTTP_X_FORWARDED_FOR',
            request.httprequest.environ.get('REMOTE_ADDR', ''),
        )
        ip_address = ip_address.split(',')[0].strip()  # first IP if comma-separated
        user_agent = (
            request.httprequest.user_agent.string
            if request.httprequest.user_agent else ''
        )

        # --- Step 6: Create OTP challenge ---
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

        # --- Step 8: Store pending auth state in session ---
        request.session[_SESSION_UID]      = uid
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
    # Internal helpers
    # -----------------------------------------------------------------------

    def _render_login_error(self, message: str, redirect=None):
        """
        Render the standard Odoo login page with an error message.

        NOTE (Odoo 18): the login template expects the key 'login_error',
        NOT 'error'. Using 'error' silently renders no message at all.
        """
        return request.render('web.login', {
            'login_error': message,
            'redirect': redirect,
        })

    @staticmethod
    def _send_otp_email(env, user, plain_otp: str):
        """Send the OTP via the Odoo mail template."""
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
    # OTP Verification — GET /auth/otp/verify
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/verify', type='http', auth='none', methods=['GET'], csrf=False, website=True)
    def otp_verify_get(self, **kwargs):
        """
        Display the OTP verification form.
        Validates session state before rendering.

        NOTE (Odoo 18): Do NOT call _auth_method_public() manually here.
        For auth='none' routes Odoo already initialises a public env; calling
        it before the session keys are read causes an AttributeError / 500.
        """
        uid          = request.session.get(_SESSION_UID)
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        db           = request.session.get(_SESSION_DB)

        if not uid or not challenge_id or db != request.db:
            _logger.warning(
                'auth.otp: GET /auth/otp/verify accessed without valid session state.'
            )
            return request.redirect('/web/login')

        env       = request.env(user=SUPERUSER_ID)
        challenge = _get_challenge(env, challenge_id, uid)

        if not challenge:
            _logger.warning(
                'auth.otp: No valid challenge found for uid=%d challenge_id=%d'
                ' — redirecting to login.',
                uid, challenge_id,
            )
            _clear_otp_session()
            return request.redirect('/web/login')

        resend_seconds = challenge.resend_seconds_remaining()
        return request.render('auth_email_otp.otp_verify_page', {
            'resend_cooldown': resend_seconds,
        })

    # -----------------------------------------------------------------------
    # OTP Verification — POST /auth/otp/verify (submit code)
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/verify', type='http', auth='none', methods=['POST'], csrf=True, website=True)
    def otp_verify_post(self, otp_code='', **kwargs):
        """
        Handle OTP submission.

        Security controls:
        - Session state validated (uid, challenge_id, db match).
        - Challenge existence and 'pending' state validated.
        - OTP stripped and length-checked (rejects obvious junk early).
        - Hash comparison delegated to model (constant-time digest).
        - On success: finalise session, set session.db, prevent fixation.
        - On failure: generic error only — no detail leaked.
        - On lockout: clear session, redirect to login with lockout message.
        """
        uid          = request.session.get(_SESSION_UID)
        challenge_id = request.session.get(_SESSION_CHALLENGE)
        redirect_url = request.session.get(_SESSION_REDIRECT, '/odoo')
        db           = request.session.get(_SESSION_DB)

        # --- Validate session state ---
        if not uid or not challenge_id or db != request.db:
            return request.redirect('/web/login')

        env       = request.env(user=SUPERUSER_ID)
        challenge = _get_challenge(env, challenge_id, uid)

        if not challenge:
            _clear_otp_session()
            return request.redirect('/web/login')

        # --- Validate input format (fast reject before hitting DB) ---
        otp_code = (otp_code or '').strip()
        if len(otp_code) != 6 or not otp_code.isdigit():
            return request.render('auth_email_otp.otp_verify_page', {
                'error': _GENERIC_ERROR,
                'resend_cooldown': challenge.resend_seconds_remaining(),
            })

        # --- Verify OTP (constant-time comparison inside model) ---
        is_valid = challenge.verify_otp(otp_code)

        if not is_valid:
            # Re-fetch to check if challenge was cancelled (lockout / expiry)
            challenge = env['auth.otp.challenge'].sudo().browse(challenge_id)

            if challenge.state == 'cancelled':
                _clear_otp_session()
                _logger.warning(
                    'auth.otp: Challenge %d for uid=%d cancelled (lockout/expiry)'
                    ' — forcing re-login.',
                    challenge_id, uid,
                )
                return request.render('web.login', {'login_error': _LOCKOUT_ERROR})

            return request.render('auth_email_otp.otp_verify_page', {
                'error': _GENERIC_ERROR,
                'resend_cooldown': challenge.resend_seconds_remaining(),
            })

        # --- OTP correct: finalise authentication ---
        _clear_otp_session()

        user = env['res.users'].browse(uid)

        # NOTE (Odoo 18): session.db MUST be set explicitly on auth='none' routes
        # before setting uid/login, otherwise the session middleware discards the
        # session as invalid and the user is immediately logged out on the next
        # request.
        request.session.db            = db
        request.session.uid           = uid
        request.session.login         = user.login
        request.session.session_token = user._compute_session_token(
            request.session.sid
        )

        # Refresh request.env so downstream code sees the correct user
        request.update_env(user=uid)

        _logger.info(
            'auth.otp: Login completed for user %s (id=%d) via 2FA.',
            user.login, uid,
        )

        return request.redirect(_safe_redirect(redirect_url))

    # -----------------------------------------------------------------------
    # OTP Resend — POST /auth/otp/resend
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/resend', type='http', auth='none', methods=['POST'], csrf=True, website=True)
    def otp_resend(self, **kwargs):
        """
        Resend OTP to the user.

        Controls:
        - 60-second cooldown enforced via model.
        - Creates a NEW challenge (old one is cancelled inside create_challenge).
        - All actions logged for audit trail.
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

        # Enforce cooldown
        if not old_challenge.can_resend():
            remaining = old_challenge.resend_seconds_remaining()
            return request.render('auth_email_otp.otp_verify_page', {
                'error': _RESEND_COOLDOWN_MSG,
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

        # Update session to point to the new challenge
        request.session[_SESSION_CHALLENGE] = new_challenge.id
        request.session.modified            = True

        _logger.info(
            'auth.otp: OTP resent for user %s (id=%d) | new_challenge_id=%d',
            user.login, uid, new_challenge.id,
        )

        return request.render('auth_email_otp.otp_verify_page', {
            'success': _RESEND_SUCCESS_MSG,
            'resend_cooldown': 60,
        })

    # -----------------------------------------------------------------------
    # Cancel / Back to login
    # -----------------------------------------------------------------------

    @http.route('/auth/otp/cancel', type='http', auth='none', methods=['GET', 'POST'], csrf=False, website=True)
    def otp_cancel(self, **kwargs):
        """Allow the user to abandon the OTP flow and return to the login page."""
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