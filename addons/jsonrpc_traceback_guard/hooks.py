# -*- coding: utf-8 -*-
import functools
import threading

import odoo.http as http


_PATCH_LOCK = threading.Lock()


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
    with _PATCH_LOCK:
        if getattr(http.serialize_exception, '_vnz18_jsonrpc_patch', False):
            return

        original_serialize_exception = http.serialize_exception

        @functools.wraps(original_serialize_exception)
        def serialize_exception_no_debug_for_public(exception):
            payload = original_serialize_exception(exception)

            try:
                data = payload.get('data') if isinstance(payload, dict) else None
                if isinstance(data, dict) and 'debug' in data:
                    req = getattr(http, 'request', None)
                    if not _allow_debug_payload(req):
                        sanitized_data = dict(data)
                        sanitized_data.pop('debug', None)
                        payload = dict(payload)
                        payload['data'] = sanitized_data
            except Exception:
                # Never let serialization hardening break normal exception handling.
                pass

            return payload

        serialize_exception_no_debug_for_public._vnz18_jsonrpc_patch = True
        http.serialize_exception = serialize_exception_no_debug_for_public
