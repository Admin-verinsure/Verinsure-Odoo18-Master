# -*- coding: utf-8 -*-
{
    "name": "LDAP Password Reset",
    "version": "18.0.1.0.0",
    "summary": "Standalone LDAP reset flow with OTP & non-blocking email send",
    "category": "Authentication",
    "author": "Your Company",
    "license": "LGPL-3",
    "depends": [
        "base",
        "website",
        "auth_ldap",
        "mail",
        "ldap_user_utils",   # our shared helpers (partner/LDAP utils)
    ],
    "data": [
        "views/mail_template.xml",
        "security/ir.model.access.csv",    # keep only if this module defines models (e.g., otp); else remove
    ],
    "assets": {
        "web.assets_frontend": [
            "ldap_password_reset/static/src/js/password_validation.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
