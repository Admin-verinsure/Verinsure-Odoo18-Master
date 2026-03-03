{
    'name': 'Payment Provider: Akahu',
    'version': '1.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Akahu Payment Integration',
    'depends': ['payment', 'account_payment'],
    'data': [
        'data/payment_provider_data.xml',
        'views/payment_provider_views.xml',
    ],
    'installable': True,
    'application': False,
}
