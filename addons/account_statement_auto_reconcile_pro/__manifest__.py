
{
    "name": "Account Statement Auto Reconcile Pro",
    "version": "1.0.0",
    "author": "Nikhil Rana",
    "category": "Accounting",
    "summary": "Enterprise-grade automatic bank reconciliation engine",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/journal_view.xml",
        "views/log_view.xml",
        "data/ir_cron.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}
