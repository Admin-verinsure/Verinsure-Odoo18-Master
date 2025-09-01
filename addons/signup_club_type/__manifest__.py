{
    "name": "Signup Program Type (server-rendered)",
    "version": "18.0.1.0",
    "depends": [
        "website",
        "auth_signup",
        "rotary_project_map",      # 👈 required for rotary_club_id / rotary_membership_id
        "ldap_reset_password"      # 👈 add this too since you inherit its templates
    ],
    "data": [
        "views/signup_form.xml",
        "views/rotary_id_edit.xml",
    ],
    "installable": True,
}
