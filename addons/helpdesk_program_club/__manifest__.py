# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk – Program Type & Club Fields',
    'version': '1.0',
    'summary': (
        'Adds Program Type and Club dropdowns (fetched from DB) to the '
        'helpdesk website builder form. Saves both to the ticket record '
        'and includes them in the notification email.'
    ),
    'category': 'Helpdesk',
    'author': 'Verinsure',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'website',
        'helpdesk',
        'website_helpdesk',
        'mail',
    ],
    'data': [
        'views/helpdesk_ticket_fields.xml',   # backend form: shows Program Type + Club on ticket
        'views/helpdesk_website_form.xml',    # frontend: injects the two <select> fields
    ],
    'assets': {
        'web.assets_frontend': [
            'helpdesk_program_club/static/src/js/helpdesk_club_fill.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
