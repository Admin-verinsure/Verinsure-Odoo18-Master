# -*- coding: utf-8 -*-
{
    'name': 'Signup with Google reCAPTCHA V2',
    'version': '18.0',
    'summary': 'Adds Google reCAPTCHA V2 to the signup form',
    'description': """
        Integrates Google reCAPTCHA V2 validation for website signup form.
        Requires 'google_recaptcha' module.
    """,
    'category': 'Website',
    'author': 'Culspot',
    'maintainer': 'Culspot',
    'website': 'https://culspot.com',
    'license': 'LGPL-3',
    'depends': ['auth_signup','website', 'google_recaptcha'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            "https://www.google.com/recaptcha/api.js?render=explicit",
                    ],
    },
    'demo': [],
    'qweb': [],
    'images': ['static/description/web_recaptcha.jpg'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
