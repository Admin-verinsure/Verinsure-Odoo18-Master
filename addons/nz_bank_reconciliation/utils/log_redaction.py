# -*- coding: utf-8 -*-
import re

REDACTED = '[REDACTED]'

_SENSITIVE_KEYS = {
    'authorization',
    'password',
    'secret',
    'client_secret',
    'access_token',
    'refresh_token',
    'api_key',
    'x-api-key',
    'app_secret',
    'app_token',
    'user_token',
    'cursor',
}

_PATTERNS = [
    (re.compile(r'(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)'), r'\1' + REDACTED),
    (re.compile(r'(?i)(\bbearer\s+)([^\s,;]+)'), r'\1' + REDACTED),
    (re.compile(r'\b(app_token_)[A-Za-z0-9_\-]+\b'), r'\1' + REDACTED),
    (re.compile(r'\b(user_token_)[A-Za-z0-9_\-]+\b'), r'\1' + REDACTED),
    (re.compile(r'(gcm1:)[A-Za-z0-9+/=_\-]+'), r'\1' + REDACTED),
    # JWT-like token: keep this intentionally strict to avoid redacting
    # normal dotted values such as version numbers (e.g. 18.0.1).
    (re.compile(r'\b[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\b'), REDACTED),
    (re.compile(r'(?i)("?(?:password|secret|client_secret|access_token|refresh_token|api_key|x-api-key|authorization|app_secret|app_token|user_token|cursor)"?\s*[:=]\s*")([^"]+)(")'), r'\1' + REDACTED + r'\3'),
    (re.compile(r"(?i)(\b(?:password|secret|client_secret|access_token|refresh_token|api_key|x-api-key|authorization|app_secret|app_token|user_token|cursor)\b\s*[:=]\s*)([^\s,;]+)"), r'\1' + REDACTED),
]


def _sanitize_string(value):
    text = value if isinstance(value, str) else str(value)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _is_sensitive_key(key):
    key_text = str(key).strip().strip('"\'').lower()
    return key_text in _SENSITIVE_KEYS


def sanitize_log_value(value):
    """Sanitize values before logging to avoid leaking credentials.

    Handles strings, exceptions, mappings, sequences, and arbitrary objects.
    """
    if value is None:
        return None

    if isinstance(value, Exception):
        return _sanitize_string('%s: %s' % (value.__class__.__name__, str(value)))

    if isinstance(value, str):
        return _sanitize_string(value)

    if isinstance(value, bytes):
        return _sanitize_string(value.decode(errors='replace'))

    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                sanitized[key] = REDACTED
            else:
                sanitized[key] = sanitize_log_value(item)
        return sanitized

    if isinstance(value, list):
        return [sanitize_log_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(sanitize_log_value(item) for item in value)

    if isinstance(value, set):
        return {sanitize_log_value(item) for item in value}

    if isinstance(value, (int, float, bool)):
        return value

    return _sanitize_string(value)
