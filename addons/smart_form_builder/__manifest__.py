{
    "name": "Forms (Standalone)",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Standalone form builder with dynamic DB dropdown options",
    "depends": ["base", "website"],
    "data": [
        "security/ir.model.access.csv",
        "views/actions.xml",
        "views/menu.xml",
        "views/form_views.xml",
        "views/field_views.xml",
        "views/submission_views.xml",
        "views/branch_rule_views.xml",
        "views/select_field_wizard_views.xml",
        "views/templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "smart_form_builder/static/src/css/sfb_dropdown.css",
            "smart_form_builder/static/src/js/smart_form_frontend.js",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
