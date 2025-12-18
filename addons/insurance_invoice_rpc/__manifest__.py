# -*- coding: utf-8 -*-
{
    "name": "Insurance RPC: Create Insurance + Invoice + Email (Cybro)",
    "version": "18.0.1.0.8",
    "category": "Insurance",
    "summary": "RPC method to create insurance.details + posted invoice + PDF email. Aligns invoice linkage with Cybro UI (Source Document).",
    "depends": ["base", "account", "mail", "insurance_management_cybro"],
    "data": [
        "views/account_move_view.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
