# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk – Program Type & Club Fields',
    'version': '1.0',
    'summary': 'Adds Program Type and Club dropdowns to the helpdesk ticket website form and shows Club on the backend ticket form',
    'category': 'Helpdesk',
    'license': 'LGPL-3',
    'depends': ['base', 'website', 'mail'],
    'data': [],
    'assets': {
        'web.assets_frontend': [
            'helpdesk_program_club/static/src/js/helpdesk_club_fill.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
