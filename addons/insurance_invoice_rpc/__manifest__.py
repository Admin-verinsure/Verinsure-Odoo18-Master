# -*- coding: utf-8 -*-
{
    "name": "Insurance RPC: Create Insurance + Invoice + Email (Cybro)",
    "version": "18.0.1.3.0",
    "category": "Insurance",
    "summary": "RPC create insurance.details + invoice + email. Links invoice under Insurance (invoice_ids). Creates new agents with required fields.",
    "depends": ["base", "account", "mail", "insurance_management_cybro"],
    "data": [
        "views/account_move_view.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
