{
    'name': 'Add Existing Contact',
    'version': '18.0.1.0.0',
    'category': 'Contacts',
    'summary': 'Add existing contacts as child contacts',
    'depends': ['contacts'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_view.xml',
        'views/add_existing_contact_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
