# -*- coding: utf-8 -*-
{
    "name": "Insurance RPC: Create Insurance + Invoice + Email (Cybro)",
    "version": "18.0.1.1.0",
    "category": "Insurance",
    "summary": "RPC create insurance.details + posted invoice + PDF email. Uses Cybro workflow confirm to assign INS/xxx then sets invoice_origin.",
    "depends": ["base", "account", "mail", "insurance_management_cybro"],
    "data": [
        "views/account_move_view.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
