{
    'name': 'Not4Profit Custom Email Template',
    'version': '1.0.0',
    'category': 'Email',
    'summary': 'Custom polished email template for all outgoing emails',
    'depends': ['mail', 'account'],
    'data': [
        'views/mail_template_view.xml',
        'data/mail_template_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
