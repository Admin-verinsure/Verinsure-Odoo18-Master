{
    "name": "Signup Program Type (server-rendered)",
    "version": "18.0.1.0",
    "depends": [
        "website",
        "auth_signup",
        "rotary_project_map",
        "ldap_reset_password",
    ],
    "data": [
        "views/signup_form.xml",
        "views/rotary_id_edit.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "signup_club_type/static/src/js/club_dynamic_fill.js",
        ],
    },
    "installable": True,
}