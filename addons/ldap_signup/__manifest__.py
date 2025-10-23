{
    "name": "LDAP Signup",
    "version": "18.0.1.0.0",
    "summary": "Standalone website signup that reuses existing LDAP entries (by email) or creates new ones",
    "depends": ["website", "auth_signup", "auth_ldap", "ldap_user_utils", "mail"],
    "data": [],
    "qweb": ["views/signup_templates.xml"],   # ← load as QWeb
    "license": "LGPL-3",
    "installable": True,
}
