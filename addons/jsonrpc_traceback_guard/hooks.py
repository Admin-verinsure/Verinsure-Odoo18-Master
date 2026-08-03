# -*- coding: utf-8 -*-
import functools
import json
import logging
import threading

import odoo.http as http
from werkzeug.wrappers import Response as WerkzeugResponse


_PATCH_LOCK = threading.Lock()
_logger = logging.getLogger(__name__)
_logger.info('VNZ-18 jsonrpc_traceback_guard hooks.py imported.')


def _allow_debug_payload(req):
    """Preserve existing debug behavior for authenticated requests."""
    try:
        if not req:
            return False
        uid = getattr(req.session, 'uid', False)
        if not uid:
            return False
        return True
    except Exception:
        return False


def post_load_hook():
    """Patch JSON-RPC exception serialization without changing core files."""
    _logger.info('VNZ-18 post_load_hook entered.')
    with _PATCH_LOCK:
        dispatcher = getattr(http, 'JsonRPCDispatcher', None)
        if not dispatcher:
            _logger.info('VNZ-18 JsonRPCDispatcher not available; skipping patch.')
            return

        original_handle_error = getattr(dispatcher, 'handle_error', None)
        if not original_handle_error:
            _logger.info('VNZ-18 JsonRPCDispatcher.handle_error not available; skipping patch.')
            return

        if getattr(original_handle_error, '_vnz18_jsonrpc_patch', False):
            _logger.info('VNZ-18 JsonRPCDispatcher.handle_error already patched; skipping.')
            return
        _logger.info(
            'VNZ-18 applying monkey patch to odoo.http.JsonRPCDispatcher.handle_error (original id=%s).',
            id(original_handle_error),
        )

        @functools.wraps(original_handle_error)
        def handle_error_no_debug_for_public(self, exception):
            _logger.info('VNZ-18 wrapped JsonRPCDispatcher.handle_error invoked.')
            response = original_handle_error(self, exception)

            try:
                req = getattr(http, 'request', None)
                if _allow_debug_payload(req):
                    return response

                if not isinstance(response, WerkzeugResponse):
                    return response

                mimetype = (getattr(response, 'mimetype', '') or '').lower()
                if 'json' not in mimetype:
                    return response

                raw = response.get_data(as_text=False)
                if not raw:
                    return response

                charset = (getattr(response, 'charset', None) or 'utf-8')
                text = raw.decode(charset)

                payload = json.loads(text)
                error = payload.get('error') if isinstance(payload, dict) else None
                data = error.get('data') if isinstance(error, dict) else None
                if isinstance(data, dict) and 'debug' in data:
                    sanitized_data = dict(data)
                    sanitized_data.pop('debug', None)
                    sanitized_error = dict(error)
                    sanitized_error['data'] = sanitized_data
                    sanitized_payload = dict(payload)
                    sanitized_payload['error'] = sanitized_error
                    response.set_data(
                        json.dumps(sanitized_payload, ensure_ascii=False).encode(charset)
                    )
            except Exception:
                # Never let response hardening break normal exception handling.
                pass

            return response

        handle_error_no_debug_for_public._vnz18_jsonrpc_patch = True
        dispatcher.handle_error = handle_error_no_debug_for_public
        _logger.info(
            'VNZ-18 monkey patch applied (wrapped id=%s).',
            id(dispatcher.handle_error),
        )
