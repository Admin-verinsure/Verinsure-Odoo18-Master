# -*- coding: utf-8 -*-
import functools
import inspect
import threading

from werkzeug.wrappers import Response as WerkzeugResponse


_PATCH_LOCK = threading.Lock()


def post_load_hook():
    """VNZ-17: harden session_id cookie defaults without touching core."""
    with _PATCH_LOCK:
        original_set_cookie = getattr(WerkzeugResponse, 'set_cookie', None)
        if not original_set_cookie:
            return

        if getattr(original_set_cookie, '_vnz17_session_cookie_patch', False):
            return

        set_cookie_signature = inspect.signature(original_set_cookie)

        @functools.wraps(original_set_cookie)
        def set_cookie_hardened(self, key, *args, **kwargs):
            # VNZ-17 Session Cookie Hardening: only affect session_id cookie.
            if key == 'session_id':
                secure_supplied = False
                samesite_supplied = False
                try:
                    bound = set_cookie_signature.bind_partial(self, key, *args, **kwargs)
                    secure_supplied = 'secure' in bound.arguments
                    samesite_supplied = 'samesite' in bound.arguments
                except TypeError:
                    # Fallback path for unexpected signature drift.
                    secure_supplied = 'secure' in kwargs
                    samesite_supplied = 'samesite' in kwargs

                if not secure_supplied:
                    kwargs['secure'] = True
                if not samesite_supplied:
                    kwargs['samesite'] = 'Lax'
            return original_set_cookie(self, key, *args, **kwargs)

        set_cookie_hardened._vnz17_session_cookie_patch = True
        WerkzeugResponse.set_cookie = set_cookie_hardened
