# -*- coding: utf-8 -*-
{
    'name': 'Customer Statement Report',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Generate Customer Statement with Net Balance Calculation',
    'description': """
        Customer Statement Report
        =========================
        Generate a complete customer statement showing:
        - Opening Balance
        - Invoices and Credit Notes in date range
        - Running Balance
        - Closing Net Balance (Amount Due / Credit Balance)

        Supports PDF (QWeb) and Excel (XLSX) export.
    """,
    'author': 'Custom',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/customer_statement_wizard_views.xml',
        'views/res_partner_views.xml',
        'report/customer_statement_report.xml',
        'report/customer_statement_template.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
