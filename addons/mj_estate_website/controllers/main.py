# -*- coding: utf-8 -*-
from datetime import date

from odoo import http
from odoo.http import request


class MJEstateHomepage(http.Controller):
    """Serves the Morris & James.Estate homepage.

    Brief-only build: this controller renders ONLY the /estate
    homepage. Nav links to VISIT / EAT / MAKE / DISCOVER / MARKET /
    LEASE / STORY / CONTACT are present in the markup per the brand
    manual's primary navigation (§19) but are not routed to real
    pages yet — they point at in-page anchors / '#' until those
    pages are commissioned, so the module never 404s on its own nav.
    """

    @http.route(
        ['/estate', '/estate/'],
        type='http', auth='public', website=True, sitemap=True,
    )
    def estate_homepage(self, **kw):
        return request.render('mj_estate_website.estate_homepage', {
            'current_year': date.today().year,
        })
