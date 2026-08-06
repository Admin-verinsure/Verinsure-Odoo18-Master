# -*- coding: utf-8 -*-
{
    'name': "Morris & James.Estate — Homepage",
    'summary': "Editorial homepage for Morris & James.Estate, Matakana — "
               "the original home of Morris & James Pottery, now an "
               "active estate for artisans, hospitality, markets and "
               "independent enterprise.",
    'description': """
Morris & James.Estate Homepage
===============================
A single, story-led homepage for the Morris & James.Estate public
website, built to the Morris & James.Estate Brand Manual (Revised
Concept, August 2026).

Route: /estate

Sections: transparent sticky header, split hero, brand story, heritage
timeline, estate experiences, estate highlights, brand values, featured
estate gallery, upcoming events, final call to action, footer.

Palette: Matakana Earth, Estate Green, Glaze Blue, Aqua Glaze, Kiln
Gold, Clay White, Kiln Ink, plus controlled glaze accents.
Typography: Cormorant Garamond (editorial) + Source Sans 3 (interface).
    """,
    'version': '18.0.1.0.0',
    'category': 'Website',
    'author': 'Morris & James.Estate',
    'website': 'https://morrisandjames.estate',
    'license': 'LGPL-3',
    'depends': ['website'],
    'data': [
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'mj_estate_website/static/src/scss/estate_variables.scss',
            'mj_estate_website/static/src/scss/estate_homepage.scss',
            'mj_estate_website/static/src/js/estate_homepage.js',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
