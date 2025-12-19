# -*- coding: utf-8 -*-
{
    "name": "Insurance RPC: Create Insurance + Invoice + Email (Cybro)",
    "version": "18.0.1.1.1",
    "category": "Insurance",
    "summary": "RPC create insurance.details + invoice + email. Links invoice to Cybro invoice_ids if that relation exists and sets invoice_origin=INS/xxx.",
    "depends": ["base", "account", "mail", "insurance_management_cybro"],
    "data": [
        "views/account_move_view.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
