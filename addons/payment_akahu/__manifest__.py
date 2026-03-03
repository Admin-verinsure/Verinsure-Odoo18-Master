{
    'name': 'Payment Provider: Akahu',
    'version': '1.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Akahu Payment Gateway Integration',
    'depends': ['payment', 'account_payment'],
    'data': [
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
    ],
    'installable': True,
    'application': False,
}
