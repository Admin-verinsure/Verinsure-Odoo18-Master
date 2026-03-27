# -*- coding: utf-8 -*-
{
    'name': 'Rotary_LDAP_Signup',
    'version': '1.1',
    'summary': 'Rotary Member and Non-Member Signup with LDAP + reCAPTCHA v2',
    'description': """
Custom signup flow for Rotary users:
 - Supports Member and Non-Member signup
 - Integrates with LDAP directory
 - Dynamically fetches Rotary Clubs and Program Types
 - Assigns appropriate roles ("Members" / "Guests")
 - Google reCAPTCHA v2 (checkbox) on all signup forms
 - Per-IP rate limiting on failed CAPTCHA attempts
 - Keys stored securely in ir.config_parameter (never hardcoded)
    """,
    'category': 'Authentication',
    'author': 'Verinsure',
    'website': 'https://www.verinsure.online',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'auth_signup',
        'auth_ldap',
        'website',
        'rotary_project_map',
    ],
    'data': [
        'data/ir_config_parameter.xml',   # reCAPTCHA keys (noupdate=1)
        'views/signup_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ldap_reset_password/static/src/js/club_dynamic_fill.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
