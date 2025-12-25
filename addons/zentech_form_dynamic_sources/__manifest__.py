{
    "name": "Zentech Form Dynamic Sources",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Auto-populate form field options from models based on field code/label (e.g., Volunteer Type -> hr.job)",
    "depends": ["base", "web", "hr"],
    "data": [
        "security/ir.model.access.csv",
        "views/zentech_form_field_inherit_views.xml"
    ],
    "installable": true,
    "application": false
}
