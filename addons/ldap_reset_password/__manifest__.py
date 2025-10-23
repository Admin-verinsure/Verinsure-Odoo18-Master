{
    'name': 'LDAP Reset Password',
    'version': '18.0.1.0.1',
    'summary': 'Add LDAP Reset Password functionality (OTP) and login overrides',
    'author': 'Verinsure',
    'depends': [
        'auth_ldap', 'auth_signup', 'base', 'web', 'website', 'mail',
        'membership', 'rotary_project_map',
        'ldap_user_utils',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/reset_ldap_password.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ldap_reset_password/static/src/js/password_validation.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
