{
    'name': 'Akahu Bank Statement',
    'version': '18.0.1.0.0',
    'summary': 'Import NZ bank transactions from Akahu',
    'description': 'This module integrates with the Akahu API to import New Zealand bank transactions into Odoo 18.',
    'category': 'Accounting',
    'author': 'Sangita Thummar',
    'depends': ['account'],
    'data': [
        'data/ir_cron.xml',
        'security/ir.model.access.csv',
        'views/import_akahu_statement_view.xml',

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

