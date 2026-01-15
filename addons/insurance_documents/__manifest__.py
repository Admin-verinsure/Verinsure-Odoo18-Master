# -*- coding: utf-8 -*-
{
    "name": "Insurance Documents (DMS Secure)",
    "version": "18.0.3.3.0",
    "category": "Insurance",
    "summary": "Insurance documents in DMS with policy linking + strict access control + technical bypass",
    "depends": ["base", "mail", "insurance_management_cybro", "dms"],
    "data": [
        "security/security.xml",
        "views/insurance_dms_views.xml",
    ],
    "installable": True,
    "application": False,
}
