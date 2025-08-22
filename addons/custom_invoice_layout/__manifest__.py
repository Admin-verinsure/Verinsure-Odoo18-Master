{
    'name': 'Custom Report Layout',
    'version': '1.0',
    'category': 'Reporting',
    'summary': 'Custom external layout inherited from project web.external_layout_standard',
    'description': """
This module duplicates Odoo18’s external layout and inherits the project layout 
(web.external_layout_standard) for applying custom changes without touching original code.
    """,
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': ['web', 'account'],
    'data': [
        'views/external_layout_standard.xml',
        'views/external_layout_inherit.xml',
        'views/report_invoice_document.xml',
    ],
    'installable': True,
    'application': False,
}
