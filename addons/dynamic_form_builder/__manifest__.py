{
    'name': 'Form Builder – Dynamic Dropdowns & Branching',
    'version': '18.0.1.0.0',
    'category': 'Tools',
    'summary': 'Extends zehntech_form_builder with dynamic dropdown sources and conditional branching to other forms',
    'depends': ['zehntech_form_builder', 'base', 'web'],
    'data': ['security/ir.model.access.csv', 'views/form_builder_field_extend_views.xml', 'views/branch_rule_views.xml', 'views/public_form_assets.xml', 'views/public_form_template_inherit.xml'],
    'assets': {'web.assets_backend': ['zt_form_builder_dynamic/static/src/js/field_dynamic_source_backend.js'], 'web.assets_frontend': ['zt_form_builder_dynamic/static/src/js/dynamic_dropdown_frontend.js', 'zt_form_builder_dynamic/static/src/js/branching_frontend.js']},
    'license': 'LGPL-3',
    'installable': True,
    'application': False
}
