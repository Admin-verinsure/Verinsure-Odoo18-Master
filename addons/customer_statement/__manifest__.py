{
    'name': 'Customer Statement Report',
    'version': '1.0',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_view.xml',
        'views/customer_statement_wizard_view.xml',
        'report/customer_statement_report.xml',
    ],
    'installable': True,
}