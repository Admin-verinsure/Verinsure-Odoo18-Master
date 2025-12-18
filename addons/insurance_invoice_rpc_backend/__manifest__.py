# -*- coding: utf-8 -*-
{
    "name": "Insurance RPC: Create Insurance + Invoice + Email (Cybro)",
    "version": "18.0.1.0.2",
    "category": "Accounting",
    "summary": "RPC method to create insurance.details, generate invoice PDF, and email it (backend-only).",
    "depends": ["base", "account", "mail", "hr", "insurance_management_cybro"],
    "data": [
        "security/security.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
