# -*- coding: utf-8 -*-
{
    'name': 'Partner Document Link (DMS)',
    'version': '18.0.2.0.0',
    'summary': 'Link DMS documents to Companies & Contacts with a smart button',
    'description': """
        Adds an explicit partner_id field to dms.file and dms.directory,
        and a Documents smart button on res.partner (Company / Contact).

        How to use:
        - Open any DMS file or directory → set "Related Partner"
        - Open any Company or Contact → click the Documents button
          to see only that partner's documents.

        The button count combines:
          1. Files directly tagged with partner_id
          2. Files inside directories tagged with partner_id
    """,
    'category': 'Documents',
    'author': 'Custom',
    'depends': [
        'base',
        'contacts',
        'dms',
    ],
    'data': [
        'views/dms_views.xml',
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
