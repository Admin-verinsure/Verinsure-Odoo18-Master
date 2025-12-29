# -*- coding: utf-8 -*-
# Part of Yantradhigam Pvt Ltd. See LICENSE file for full copyright and licensing details.

{
    'name': 'Partner Contact Type Management',
    'version': '18.0.1.0.0',
    'category': 'Contacts',
    'summary': 'Manage partner contact types with categories like Customer, Vendor, etc.',
    'description': """
Partner Contact Type Management
===============================

This module allows you to:
* Create and manage contact types (Customer, Vendor, Distributor, etc.)
* Assign multiple contact types to partners
* Filter and search partners by contact type
* Generate automatic contact codes
* Enhanced partner management workflow

Features:
---------
* Automatic sequence generation for contact codes
* Many-to-many relationship between partners and contact types
* Enhanced search and filter capabilities
* Tree, form, and kanban views
* Integration with existing partner workflow

Author: YantrAdhigam Labs Pvt Ltd
Website: https://www.yantradhigam.com
Support: odoo@yalabs.in
    """,
    'author': 'YantrAdhigam Labs Pvt Ltd',
    'website': 'https://www.yantradhigam.com',
    'support': 'odoo@yalabs.in',
    'depends': ['contacts'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'views/partner_contact_type_views.xml',
        'views/res_partner_views.xml',
    ],
    'demo': [
        'demo/partner_contact_type_demo.xml',
    ],
    'images': ['static/description/module.png', 'static/description/icon.png'],
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': "LGPL-3",
}