{
    "name": "Akahu Import & Auto Reconcile (Odoo 18)",
    "version": "1.0.0",
    "category": "Accounting",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/wizard_view.xml",
        "views/log_view.xml",
        "data/ir_cron.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}