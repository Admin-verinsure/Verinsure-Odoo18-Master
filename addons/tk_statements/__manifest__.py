# -*- coding: utf-8 -*-
{
    'name': 'Customer Statement Report | Customer Statement Aging',
    'description': """
            Customer Statement Report with Running Balance, Opening Balance,
            Credit Notes, Partial Payments, PDF and Excel export.
    """,
    'summary': 'Customer Statement Report',
    'version': '2.0',
    'category': 'Accounting',
    'author': 'TechKhedut Inc.',
    'company': 'TechKhedut Inc.',
    'maintainer': 'TechKhedut Inc.',
    'website': "https://www.techkhedut.com",
    'depends': [
        'contacts',
        'account',
        'web',
    ],
    'data': [
        # Security
        'security/security_access.xml',
        'security/ir.model.access.csv',
        # Wizard
        'wizard/customer_statement_view.xml',
        # Report
        'report/customer_statement_report_pdf.xml',
        # Views
        'views/menus.xml',
    ],
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
