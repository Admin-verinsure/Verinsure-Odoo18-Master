# -*- coding: utf-8 -*-
{
    'name': 'LDAP Signup',
    'version': '1.0',
    'summary': 'Rotary Member and Non-Member Signup using LDAP integration',
    'description': """
Custom signup flow for Rotary users:
 - Supports Member and Non-Member signup
 - Integrates with LDAP directory
 - Dynamically fetches Rotary Clubs and Program Types
 - Assigns appropriate roles ("Members" / "Guests")
    """,
    'category': 'Authentication',
    'author': 'Verinsure',
    'website': 'https://www.verinsure.online',
    'license': 'LGPL-3',
    'depends': [
        'auth_signup',
        'website',
        'ldap_reset_password',  # ✅ depends on existing reset-password module
    ],
    'data': [
        'views/signup_templates.xml',  # XML templates for signup pages
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
