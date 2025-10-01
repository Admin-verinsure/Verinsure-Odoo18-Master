# invoice_poc/__manifest__.py
{
    "name": "Invoice POC",
    "summary": "Store payload, create & post customer invoice",
    "version": "18.0.1.0.0",
    "author": "Your Team",
    "license": "LGPL-3",
    "depends": ["base", "account"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "application": False,
    "installable": True,
}
