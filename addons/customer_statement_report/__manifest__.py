# -*- coding: utf-8 -*-
{
    'name': 'Customer Statement Report',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Dynamic Customer Statement Reports with filters and PDF/Excel export',
    'description': """
        Customer Statement Report Module for Odoo 18
        =============================================
        Features:
        - Dynamic customer statement generation
        - Filter by date range, journals, and currencies
        - Shows opening balance, transactions, and closing balance
        - PDF and Excel export
        - Available in Customers action menu
        - Aged balance summary
        - Professional report layout
    """,
    'author': 'Custom Development',
    'depends': ['account', 'base'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/customer_statement_wizard_views.xml',
        'report/customer_statement_report_template.xml',
        'report/customer_statement_report.xml',
        'views/res_partner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'customer_statement_report/static/src/css/customer_statement.css',
        ],
        'web.report_assets_common': [
            'customer_statement_report/static/src/css/report_style.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'application': False,
}
