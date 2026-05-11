{
    "name": "Helpdesk – Program Type & Club Fields",
    "version": "18.0.1.0.0",
    "summary": "Adds Program Type and Club Name dropdowns (DB-driven, dynamic) to the Helpdesk website form",
    "author": "Custom",
    "depends": [
        "helpdesk",
        "odoo_website_helpdesk",
        "signup_club_type",
    ],
    "data": [
        "views/helpdesk_ticket_form.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "helpdesk_program_club/static/src/js/helpdesk_club_picker.js",
        ],
    },
    "installable": True,
    "license": "LGPL-3",
}
