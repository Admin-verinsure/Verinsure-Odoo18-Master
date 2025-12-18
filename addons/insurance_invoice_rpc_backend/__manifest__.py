# -*- coding: utf-8 -*-
{
    "name": "Insurance: Create Insurance + Invoice + Email (RPC backend)",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "summary": "RPC method to create insurance.details + invoice + email PDF from JSON payload",
    "description": "Backend-only helper module. Adds an XML-RPC callable method on insurance.details to create/update partner and employee, create insurance, create+post invoice, render PDF and email it.",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["base", "mail", "account", "insurance"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False
}
