{
    'name': 'Membership Rotary Modifications',
    'version': '18.0.1.0.0',
    'category': 'Membership',
    'summary': 'Changes to membership module for Rotary NZ.',
    'sequence': 10,
    'license': '',
    'author': 'Verinsure',
    'website': 'verinsure.online',
    'depends': ['base', 'membership', 'ldap_reset_password'],
    'data': [
        'views/res_partner_view.xml',
        # include any other data files you have
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
