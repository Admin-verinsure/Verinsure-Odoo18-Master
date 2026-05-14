# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk – Program Type & Club Fields',
    'version': '1.1',
    'summary': 'Adds Program Type and Club Name to helpdesk tickets (frontend form + backend views)',
    'category': 'Helpdesk',
    'license': 'LGPL-3',
    'depends': ['base', 'helpdesk', 'website', 'mail'],
    'data': [
        'views/helpdesk_ticket_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'helpdesk_program_club/static/src/js/helpdesk_club_fill.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
