# -*- coding: utf-8 -*-
{
    'name': 'Partner Document Link (DMS)',
    'version': '18.0.1.0.0',
    'summary': 'Smart button on Company/Contact to navigate to DMS files',
    'description': """
        Adds a Documents smart button on the res.partner form view
        (Company & Contact) linked to OCA DMS (dms.file / dms.directory).

        Files are associated to a partner via the standard Odoo
        res_model / res_id mechanism used by OCA DMS.
    """,
    'category': 'Documents',
    'author': 'Custom',
    'depends': [
        'base',
        'contacts',
        'dms',          # OCA Document Management System
    ],
    'data': [
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
