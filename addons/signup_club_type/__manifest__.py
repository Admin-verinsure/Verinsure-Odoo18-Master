{
    'name': 'Signup Club Type',
    'version': '1.0',
    'summary': 'Adds Program Type (Club Type) field in signup form',
    'depends': ['auth_signup'],   # depends on auth_signup
    'data': [
        'views/signup_form.xml',
    ],
    'installable': True,
    'application': False,
}
