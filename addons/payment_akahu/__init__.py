from . import models
from . import controllers

from odoo.addons.payment import setup_provider

def post_init_hook(cr, registry):
    from odoo.api import Environment
    env = Environment(cr, 1, {})
    setup_provider(env, 'akahu')
