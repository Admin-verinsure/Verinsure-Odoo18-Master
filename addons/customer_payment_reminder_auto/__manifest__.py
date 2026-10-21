{
    'name': 'Customer Payment Reminder Automation',
    'version': '18.0.1.3.0',
    'category': 'Accounting',
    'summary': 'Automated customer payment reminders based on outstanding receivables.',
    'description': """
Automated customer payment reminders
====================================

Sends reminder emails for customers with outstanding receivable balances,
with configurable threshold, cooldown, dry-run mode, and reminder history.
    """,
    'author': 'Verinsure Ltd',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/payment_reminder_log_views.xml',
        'views/payment_reminder_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}