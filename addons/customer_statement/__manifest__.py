{
    'name': 'Customer Statement',
    'version': '1.1',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/statement_wizard_view.xml',
        'report/statement_report.xml',
        'report/statement_template.xml',
    ],
    'installable': True,
}