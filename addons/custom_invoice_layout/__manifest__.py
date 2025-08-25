{
    'name': 'My Custom Invoice',
    'version': '18.0.1.0.0',
    'summary': 'Provides a custom invoice template and makes it the default.',
    'description': """
        This module creates a new, standalone invoice template and
        configures Odoo to use it as the main default invoice report.
    """,
    'author': 'Your Name',
    'website': 'https://www.yourwebsite.com',
    'category': 'Accounting/Invoicing',
    'license': 'LGPL-3',
    'depends': [
        'account',
    ],
    'data': [
        'reports/custom_external_layout.xml',   # load layout first
        'reports/invoice_report.xml',           # load invoice template
        'data/default_invoice_report.xml',      # override report action last
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
