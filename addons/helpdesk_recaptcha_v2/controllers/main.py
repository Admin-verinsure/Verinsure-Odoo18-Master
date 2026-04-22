# -*- coding: utf-8 -*-
"""
Helpdesk reCAPTCHA – Controller
================================
Overrides Odoo 18's WebsiteForm controller to inject reCAPTCHA v3
validation **exclusively** for helpdesk.ticket form submissions.

All other website forms (Contact Us, Event Registration, …) are
completely unaffected — they bypass this logic on the very first line.

Odoo 18 compatibility notes
────────────────────────────
• `request.make_json_response()` is the correct Odoo 18 API
  (replaces the older werkzeug Response pattern).
• We import WebsiteForm from `website.controllers.form` which is the
  correct path in Odoo 18 (was `website.controllers.main` in older versions).
• `@http.route()` with no arguments inherits the parent route definition.
• `ir.config_parameter` keys `recaptcha.secret_key` and `recaptcha.min_score`
  are written by Odoo's own `website_recaptcha` module — we read, never write.
"""

import json
import logging
import urllib.request
import urllib.parse
import urllib.error

from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm

_logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
HELPDESK_MODEL      = 'helpdesk.ticket'
RECAPTCHA_VERIFY_URL = 'https://www.google.com/recaptcha/api/siteverify'
RECAPTCHA_TIMEOUT   = 5   # seconds before we give up on Google's API


# ── Helpers ───────────────────────────────────────────────────────────────────

def _call_google_siteverify(secret_key: str, token: str, remote_ip: str) -> dict:
    """
    Calls Google's server-side siteverify endpoint.

    Returns the parsed JSON dict.  On any network / decode error it
    returns {'success': False, 'error-codes': ['network-error']} so the
    caller always has a consistent shape to inspect.
    """
    payload = urllib.parse.urlencode({
        'secret':   secret_key,
        'response': token,
        'remoteip': remote_ip,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(
            RECAPTCHA_VERIFY_URL,
            data=payload,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=RECAPTCHA_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError) as exc:
        _logger.error(
            '[helpdesk_recaptcha] Network error contacting siteverify: %s', exc
        )
        return {'success': False, 'error-codes': ['network-error']}
    except (json.JSONDecodeError, ValueError) as exc:
        _logger.error(
            '[helpdesk_recaptcha] Could not decode siteverify response: %s', exc
        )
        return {'success': False, 'error-codes': ['invalid-response']}


def _json_error(code: str):
    """
    Builds a JSON 400 response that the frontend JS watches for.
    Using JSON (not redirect) preserves the user's form data.
    """
    messages = {
        'missing-input-response': (
            'Please complete the CAPTCHA before submitting.'
        ),
        'invalid-input-response': (
            'The CAPTCHA response is invalid. Please refresh and try again.'
        ),
        'timeout-or-duplicate': (
            'The CAPTCHA has expired. Please submit the form again.'
        ),
        'score-too-low': (
            'We could not verify that you are human. Please try again.'
        ),
        'network-error': (
            'CAPTCHA verification failed due to a network issue. Please try again.'
        ),
    }
    user_msg = messages.get(
        code,
        'CAPTCHA verification failed. Please try again.',
    )
    # `make_json_response` is the correct Odoo 18 helper (werkzeug Response
    # with Content-Type: application/json and automatic JSON serialisation).
    return request.make_json_response(
        {'error': user_msg, 'captcha_error': True},
        status=400,
    )


# ── Controller ────────────────────────────────────────────────────────────────

class HelpdeskWebsiteForm(WebsiteForm):
    """
    Thin subclass of Odoo's WebsiteForm.

    Only `website_form` is overridden.  The file-upload endpoint and all
    other methods on WebsiteForm delegate to the parent unchanged.
    """

    @http.route()   # No arguments → inherits route, methods, auth, csrf from parent
    def website_form(self, model_name, **kwargs):
        """
        Entry point for all /website/form/<model_name> POST requests.

        Fast path (non-helpdesk)
        ────────────────────────
        Any model other than helpdesk.ticket is forwarded to super()
        immediately.  Zero overhead, zero risk of breaking Contact Us etc.

        Helpdesk path
        ─────────────
        1. Extract g-recaptcha-response from kwargs and remove it so the
           ORM never sees an unknown field name.
        2. Read secret key from Odoo's own ir.config_parameter record
           (same key that Settings → Integrations → reCAPTCHA writes to).
        3. Call Google's siteverify endpoint.
        4. For v3 tokens, also check the numeric score against the
           configured minimum (default 0.5 from Odoo's own setting).
        5. On failure → JSON 400 with captcha_error: true.
        6. On success → delegate to super() which creates the ticket.
        """

        # ── Fast path: leave every other form completely alone ─────────────
        if model_name != HELPDESK_MODEL:
            return super().website_form(model_name, **kwargs)

        # ── 1. Extract token BEFORE super() sees kwargs ────────────────────
        #    The hidden field name is 'g-recaptcha-response'; Odoo's own
        #    website_recaptcha JS injects this into the form data.
        captcha_token = kwargs.pop('g-recaptcha-response', '').strip()

        # ── 2. Read keys from Odoo's native ir.config_parameter ───────────
        ICP = request.env['ir.config_parameter'].sudo()
        secret_key = ICP.get_param('recaptcha.secret_key', default='')
        min_score  = float(ICP.get_param('recaptcha.min_score', default='0.5'))

        # If keys are not configured yet, warn and let the form through
        # (avoids a broken form before the admin has set up keys).
        if not secret_key:
            _logger.warning(
                '[helpdesk_recaptcha] recaptcha.secret_key is not configured. '
                'Skipping CAPTCHA validation for helpdesk.ticket submission.'
            )
            return super().website_form(model_name, **kwargs)

        # ── 3. Reject immediately if no token was submitted ────────────────
        if not captcha_token:
            _logger.warning(
                '[helpdesk_recaptcha] Helpdesk form submitted without a '
                'reCAPTCHA token (IP: %s)',
                request.httprequest.remote_addr,
            )
            return _json_error('missing-input-response')

        # ── 4. Verify with Google ──────────────────────────────────────────
        result = _call_google_siteverify(
            secret_key=secret_key,
            token=captcha_token,
            remote_ip=request.httprequest.remote_addr or '',
        )

        _logger.debug('[helpdesk_recaptcha] siteverify result: %s', result)

        if not result.get('success'):
            error_codes = result.get('error-codes') or ['unknown']
            _logger.warning(
                '[helpdesk_recaptcha] CAPTCHA failed for IP %s: %s',
                request.httprequest.remote_addr,
                error_codes,
            )
            return _json_error(error_codes[0])

        # ── 5. Score check (v3 only – v2 tokens do not include a score) ────
        score = result.get('score')
        if score is not None:
            if score < min_score:
                _logger.warning(
                    '[helpdesk_recaptcha] reCAPTCHA v3 score %.2f below '
                    'threshold %.2f for IP %s',
                    score, min_score,
                    request.httprequest.remote_addr,
                )
                return _json_error('score-too-low')

        # ── 6. All checks passed → create the ticket normally ──────────────
        return super().website_form(model_name, **kwargs)
