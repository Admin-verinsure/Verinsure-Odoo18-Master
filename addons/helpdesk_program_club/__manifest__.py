# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk – Program Type & Club Fields',
    'version': '1.0',
    'summary': 'Adds Program Type and Club dropdowns to the helpdesk ticket website form',
    'category': 'Helpdesk',
    'author': 'Verinsure',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'website',
        'helpdesk',
        'mail',
    ],
    'data': [
        # Backend ticket form fields — comment out if install fails due to unknown ref
        # 'views/helpdesk_ticket_fields.xml',

        # Website form template (QWeb inheritance — belt-and-suspenders alongside the hook)
        'views/helpdesk_website_form.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'helpdesk_program_club/static/src/js/helpdesk_club_fill.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
