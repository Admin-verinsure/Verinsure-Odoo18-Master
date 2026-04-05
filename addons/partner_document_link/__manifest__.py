# -*- coding: utf-8 -*-
{
    'name': 'Partner Document Link (DMS)',
    'version': '18.0.3.0.0',
    'summary': 'Smart button on Company/Contact linking to their DMS documents',
    'category': 'Documents',
    'author': 'Custom',
    'depends': ['base', 'contacts', 'dms'],
    'data': [
        'views/dms_file_form_view.xml',
        'views/dms_directory_form_view.xml',
        'views/res_partner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'partner_document_link/static/src/css/partner_document_button.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
