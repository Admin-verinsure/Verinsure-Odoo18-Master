{
    "name": "Insurance Policy-first Invoice (RPC)",
    "version": "18.0.1.0.5",
    "category": "Insurance",
    "summary": "Create policy + insurance + invoice from JSON payload (policy-first)",
    "depends": ["base", "mail", "account", "product"],
    "data": ["security/ir.model.access.csv"],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
