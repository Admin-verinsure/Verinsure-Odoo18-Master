{
    "name": "LDAP Signup",
    "version": "18.0.1.0.0",
    "summary": "Website signup backed by LDAP (reuses/creates LDAP entries)",
    "depends": [
        "website", "web",
        "auth_signup", "auth_ldap",
        "mail", "membership", "rotary_project_map",
        "ldap_user_utils",
    ],
    "data": [
        "views/signup_templates.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
}
