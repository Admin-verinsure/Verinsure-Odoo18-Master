{
    "name": "Helpdesk – Program Type & Club Fields",
    "version": "18.0.1.0.0",
    "summary": "Standalone: adds Program Type and Club Name dropdowns to the Helpdesk website form",
    "author": "Custom",
    "depends": [
        "helpdesk",
        "website",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/program_type_menu.xml",
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
