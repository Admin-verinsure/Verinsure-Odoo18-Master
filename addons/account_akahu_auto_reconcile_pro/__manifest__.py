{
    "name": "Akahu Import & Auto Reconcile Pro",
    "version": "1.0.0",
    "category": "Accounting",
    "summary": "Akahu import + automatic reconciliation (Odoo 18)",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/journal_view.xml",
        "views/log_view.xml",
        "views/wizard_view.xml",
        "data/ir_cron.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}