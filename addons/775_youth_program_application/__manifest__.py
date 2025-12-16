{
    "name": "775 Youth Program Volunteer Application (Portal)",
    "version": "18.0.1.0.0",
    "summary": "Portal-only volunteer application with branched sections (Home Stay) and privacy-controlled Section 1B",
    "category": "Website/Portal",
    "license": "LGPL-3",
    "author": "Custom",
    "depends": ["portal", "website", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/volunteer_application_views.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "775_youth_program_application/static/src/js/portal_form.js",
        ],
    },
    "application": True,
    "installable": True
}
