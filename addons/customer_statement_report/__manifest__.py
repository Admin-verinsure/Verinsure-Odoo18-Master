{
    'name': 'Customer Statement Report',
    'version': '1.0',
    'summary': 'Customer Statement with Invoice + Credit Note Net Calculation',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_view.xml',
        'wizard/statement_wizard_view.xml',
        'report/statement_report.xml'
    ],
    'installable': True,
    'application': False
}