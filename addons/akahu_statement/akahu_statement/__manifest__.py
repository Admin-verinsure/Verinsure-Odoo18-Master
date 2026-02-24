{
    'name': 'Akahu Statement',
    'version': '18.0.1.0.0',
    'summary': 'Import NZ bank transactions from Akahu',
    'description': 'Import NZ bank transactions from Akahu.',
    'category': 'Accounting',
    'author': 'Verinsure',
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

