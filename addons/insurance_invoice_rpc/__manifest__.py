{
    "name": "Insurance Policy-first Invoice (POC)",
    "version": "18.0.1.0.1",
    "category": "Insurance",
    "summary": "Create policy + insurance + invoice from JSON payload (policy-first)",
    "depends": ["base", "mail", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/mail_template.xml",
        "views/invoice_payload_views.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
