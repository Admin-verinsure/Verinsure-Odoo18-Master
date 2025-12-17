# -*- coding: utf-8 -*-
{
    "name": "Dynamic Form Builder (Portal)",
    "summary": "Build portal forms with sections and conditional branching (Odoo 18)",
    "version": "18.0.1.0.1",
    "category": "Website/Portal",
    "license": "LGPL-3",
    "author": "Custom",
    "website": "",
    "depends": ["base", "mail", "portal", "website"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",

        "views/form_template_views.xml",
        "views/form_submission_views.xml",
        "views/menu.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "dynamic_form_builder_portal/static/src/js/portal_form.js",
            "dynamic_form_builder_portal/static/src/scss/portal_form.scss",
        ],
    },
    "application": True,
    "installable": True,
}
