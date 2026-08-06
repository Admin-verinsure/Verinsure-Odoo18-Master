# -*- coding: utf-8 -*-
{
    'name': 'Morris & James Estate - Website Homepage',
    'version': '18.0.1.0.0',
    'category': 'Website',
    'summary': 'Sample branded homepage built to the Morris & James Estate brand manual',
    'description': """
        Reference implementation of a custom Odoo Website homepage:
        - QWeb template with editable (oe_structure) regions for the Website Builder
        - Brand SCSS (colours, type) loaded as a website asset bundle
        - Menu items matching the brand manual's primary navigation
        This is a SAMPLE for development reference, not a finished module.
    """,
    'depends': ['website'],
    'data': [
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'morris_james_estate/static/src/scss/estate_brand.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
