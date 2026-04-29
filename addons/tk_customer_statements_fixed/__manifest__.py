# -*- coding: utf-8 -*-
{
    'name': 'Customer Statement Report | Customer Statement Aging',
    'description': """
            Customer Statement Report
    """,
    'summary': 'Customer Statement Report',
    'version': '1.0',
    'category': 'Customer',
    'author': 'TechKhedut Inc.',
    'company': 'TechKhedut Inc.',
    'maintainer': 'TechKhedut Inc.',
    'website': "https://www.techkhedut.com",
    'depends': [
        'contacts',
        'account',
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
