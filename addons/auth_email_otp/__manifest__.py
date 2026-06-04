# -*- coding: utf-8 -*-
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

{
    'name': 'Two-Factor Authentication via Email OTP',
    'version': '18.0.1.0.0',
    'category': 'Authentication',
    'summary': 'Secure Email-based One-Time Password (OTP) 2FA for Odoo 18',
    'description': """
Email OTP Two-Factor Authentication
=====================================
Adds enterprise-grade two-factor authentication to Odoo 18 Community Edition.

Features:
- Per-user opt-in 2FA toggle (admin-only)
- Secure OTP generation via Python secrets module
- SHA-256 hashed OTP storage (never plain-text)
- 5-minute OTP expiry
- 5-attempt brute-force lockout
- Replay attack prevention
- Session fixation prevention
- CSRF protection on all forms
- Professional responsive OTP UI
- Full audit logging
- Scheduled cleanup of expired records
- Multi-company and multi-website support
- Translation-ready email template
    """,
    'author': 'Custom Development',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'mail',
        'base_setup',
        'auth_signup',
    ],
    'data': [
        # 1. ACL first — ir.model.access.csv only needs the model to exist
        #    in ir_model (done by ORM before any XML loads).
        'security/ir.model.access.csv',

        # 2. Views — loads field definitions, menus, actions.
        'views/res_users_views.xml',
        'views/auth_otp_challenge_views.xml',
        'views/otp_templates.xml',
        'views/assets.xml',

        # 3. Record rules AFTER views — model_id resolved via search=,
        #    but loading after views gives the ORM the best chance to have
        #    written the ir.model row before we reference it.
        'security/auth_otp_security.xml',

        # 4. Data that references the model (mail template, cron).
        #    model_id also uses search= here for the same reason.
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'auth_email_otp/static/src/css/otp_form.css',
            'auth_email_otp/static/src/js/otp_timer.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
