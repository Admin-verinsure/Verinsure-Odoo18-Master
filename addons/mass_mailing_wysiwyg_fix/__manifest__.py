# -*- coding: utf-8 -*-
{
    'name': 'Mass Mailing WYSIWYG Fix',
    'version': '18.0.1.0.0',
    'summary': 'Fix Mass Mailing WYSIWYG lazy bundle loading in Odoo 18',
    'category': 'Marketing/Email Marketing',
    'author': 'Verinsure Limited',
    'license': 'LGPL-3',
    'depends': [
        'mass_mailing',
        'web_editor',
    ],
    'assets': {
        'web.assets_backend': [
            'mass_mailing_wysiwyg_fix/static/src/js/mass_mailing_html_field_patch.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
