# -*- coding: utf-8 -*-
{
    "name": "Contacts: Show Only Person Name (Parent Linked)",
    "version": "18.0.2.0.0",
    "category": "Contacts",
    "summary": "For child contacts (persons) linked to a parent company, show only the person's name (no company prefix).",
    "depends": ["contacts"],
    "data": [
        "security/ir.model.access.csv",
        "views/link_existing_contacts_wizard.xml",
        "views/res_partner_form_link_existing.xml"
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False
}
