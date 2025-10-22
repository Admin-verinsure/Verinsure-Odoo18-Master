{
    "name": "LDAP Password Reset",
    "version": "18.0.1.0.0",
    "summary": "Standalone LDAP reset flow with OTP & async email",
    "depends": ["website", "auth_ldap", "mail", "ldap_user_utils"],
    "data": [
        "views/mail_template.xml",
        "views/reset_templates.xml",
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_frontend": [
            "ldap_password_reset/static/src/js/password_validation.js",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
}
