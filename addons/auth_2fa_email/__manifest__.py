# -*- coding: utf-8 -*-
{
    'name': 'Two-Factor Authentication (Email OTP)',
    'version': '18.0.1.0.0',
    'summary': 'Email-based OTP two-factor authentication for Odoo 18 login',
    'description': """
        Adds a second authentication step after username/password login.
        A 6-digit OTP is sent to the user's email and must be verified
        before access is granted. OTP expires in 10 minutes.
    """,
    'author': 'Custom',
    'category': 'Authentication',
    'depends': ['web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/email_template.xml',
        'views/res_users_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'auth_2fa_email/static/src/css/otp_login.css',
            'auth_2fa_email/static/src/js/otp_login.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
