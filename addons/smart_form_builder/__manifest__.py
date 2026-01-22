{
    "name": "Smart Form Builder",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Standalone form builder with dynamic DB dropdowns and branching",
    "depends": ["base", "website"],
    "data": [
        "security/ir.model.access.csv",
        "views/actions.xml",
        "views/menu.xml",
        "views/form_views.xml",
        "views/field_views.xml",
        "views/branch_rule_views.xml",
        "views/submission_views.xml",
        "views/templates.xml"
    ],
    "assets": {
        "web.assets_frontend": [
            "smart_form_builder/static/src/js/dynamic_options.js",
            "smart_form_builder/static/src/js/branching.js"
        ]
    },
    "application": True,
    "installable": True
}