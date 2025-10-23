{
  "name": "LDAP Signup",
  "version": "18.0.1.0.0",
  "summary": "Website signup that reuses existing LDAP entries (by email) or creates new ones",
  "depends": ["website", "auth_signup", "auth_ldap", "ldap_user_utils", "mail"],
  "data": [
    "views/signup_templates.xml"
  ],
  "license": "LGPL-3",
  "installable": True,
}
