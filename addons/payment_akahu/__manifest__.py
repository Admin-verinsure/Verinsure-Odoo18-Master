{
    'name': 'Payment Provider: Akahu',
    'version': '1.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Akahu Open Banking & Payment Integration',
    'depends': ['payment', 'account_payment'],
    'data': [
        'views/payment_provider_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
