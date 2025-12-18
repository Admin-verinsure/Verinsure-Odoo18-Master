# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID

def post_init_hook(env):
    """Odoo 18 calls post_init_hook(env) with a single env."""

    # Run as superuser
    env = env(user=SUPERUSER_ID)

    # If model doesn't exist, do nothing
    if 'employee.details' not in env:
        return

    Model = env['ir.model'].sudo()
    Fields = env['ir.model.fields'].sudo()

    model = Model.search([('model', '=', 'employee.details')], limit=1)
    if not model:
        return

    # IMPORTANT: custom (manual) fields must start with x_
    field_name = 'x_partner_id'

    existing = Fields.search([('model_id', '=', model.id), ('name', '=', field_name)], limit=1)
    if existing:
        return

    Fields.create({
        'name': field_name,
        'field_description': 'Related Partner',
        'ttype': 'many2one',
        'relation': 'res.partner',
        'model_id': model.id,
        'required': False,
        'readonly': False,
        'index': True,
        'on_delete': 'set null',
        'state': 'manual',
    })
