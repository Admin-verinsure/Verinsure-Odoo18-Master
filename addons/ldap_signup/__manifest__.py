{
    'name': 'LDAP Signup',
    'version': '1.0',
    'summary': 'User signup through LDAP',
    'description': 'Allows user registration using LDAP integration.',
    'category': 'Authentication',
    'depends': ['auth_signup', 'auth_ldap', 'website', 'ldap_reset_password'],
    'data': [
        'views/signup_templates.xml',
    ],
    'installable': True,
    'application': False,
}
