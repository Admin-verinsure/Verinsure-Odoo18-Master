# -*- coding: utf-8 -*-
{
    'name': 'Partner Document Link',
    'version': '18.0.1.0.0',
    'summary': 'Link Documents to Companies & Contacts',
    'description': """
        Adds a smart button on the res.partner (Company/Contact) form view
        to navigate directly to related documents in the Documents module.
        Supports filtering documents by partner (company or contact).
    """,
    'category': 'Documents',
    'author': 'Custom',
    'depends': [
        'base',
        'contacts',
        'documents',          # Odoo Enterprise Documents module
    ],
    'data': [
        'views/res_partner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'partner_document_link/static/src/js/partner_document_button.js',
            'partner_document_link/static/src/xml/partner_document_button.xml',
            'partner_document_link/static/src/css/partner_document_button.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
