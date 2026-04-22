# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk reCAPTCHA Protection',
    'version': '18.0.1.0.0',
    'summary': 'Adds Google reCAPTCHA v3 to the Helpdesk website form only',
    'description': """
        Protects the Helpdesk website ticket-submission form with Google
        reCAPTCHA v3 using Odoo 18's native recaptcha infrastructure.

        - Reuses keys already configured in Settings → Integrations → reCAPTCHA
        - Validates server-side only for helpdesk.ticket – all other forms unchanged
        - Inline error display without page reload
        - No duplicate settings UI
    """,
    'category': 'Helpdesk',
    'author': 'Your Company',
    'website': 'https://yourcompany.com',
    'license': 'LGPL-3',

    'depends': [
        'helpdesk',
        'website_helpdesk',
        'website_recaptcha',   # Odoo 18 native module – provides keys + JS
    ],

    'data': [
        'views/helpdesk_form_recaptcha.xml',
    ],

    'assets': {
        'web.assets_frontend': [
            'helpdesk_recaptcha/static/src/js/helpdesk_recaptcha.js',
            'helpdesk_recaptcha/static/src/css/helpdesk_recaptcha.css',
        ],
    },

    'installable': True,
    'application': False,
    'auto_install': False,
}
