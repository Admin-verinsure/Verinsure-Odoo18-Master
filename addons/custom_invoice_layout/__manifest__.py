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
        'web',
    ],
    'data': [
        'reports/invoice_report.xml',
        'data/default_invoice_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
