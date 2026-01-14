# -*- coding: utf-8 -*-
{
    "name": "Insurance Documents & Policy Access",
    "version": "18.0.2.0.0",
    "category": "Insurance",
    "summary": "Insurance documents with club/owner visibility + policy visibility rules",
    "depends": ["base", "mail", "insurance_management_cybro"],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "views/insurance_document_views.xml",
        "views/insurance_details_views.xml",
        "views/res_users_views.xml",
    ],
    "installable": True,
    "application": False,
}
