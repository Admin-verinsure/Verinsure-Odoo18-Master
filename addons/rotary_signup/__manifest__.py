# -*- coding: utf-8 -*-
{
    'name': 'Rotary_LDAP_Signup',
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
        'base',
        'auth_signup',
        'auth_ldap',             
        'website',
        'rotary_project_map',     
    ],
    'data': [
        'views/signup_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ldap_reset_password/static/src/js/club_dynamic_fill.js',
        ],
    },
    'installable': True,
    'application': True,   # ← gives you an app icon and shows in Apps
    'auto_install': False,
}
