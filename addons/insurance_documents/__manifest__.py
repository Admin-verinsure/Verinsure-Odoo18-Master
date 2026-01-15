# -*- coding: utf-8 -*-
{
    "name": "Insurance Documents (DMS Secure)",
    "version": "18.0.3.2.0",
    "category": "Insurance",
    "summary": "Insurance docs in DMS (dms.file) with policy linking + policy visibility + technical bypass",
    "depends": ["base", "mail", "insurance_management_cybro", "dms"],
    "data": [
        "security/security.xml",
        "views/insurance_dms_views.xml",
    ],
    "installable": True,
    "application": False,
}
