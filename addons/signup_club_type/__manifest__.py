{
    "name": "Signup Program Type (server-rendered)",
    "version": "18.0.1.0",
    "category": "Website",
    "summary": "Extend signup form with Program Type and Club filtering",
    "author": "Your Company",
    "depends": [
        "website",
        "auth_signup",
        "rotary_project_map",     
        "ldap_reset_password"      
    ],
    "data": [
        "views/signup_form.xml",
        "views/rotary_id_edit.xml",
        "views/custom_signup.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "signup_club_type/static/src/js/club_filter.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
