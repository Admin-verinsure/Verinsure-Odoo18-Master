# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID

def post_init_hook(env):
    """Post-init hook (Odoo 18 calls this with a single `env` argument).

    Goal: ensure `employee.details` has a `partner_id` field if that model exists.
    This prevents crashes when an ir.rule/domain references employee.details.partner_id.

    We create a *manual* ir.model.fields entry only if the field doesn't already exist.
    """
    # Make sure we run with superuser privileges
    env = env(su=True)

    # If the model doesn't exist in this DB, do nothing.
    if 'employee.details' not in env:
        return

    Model = env['ir.model'].sudo()
    Fields = env['ir.model.fields'].sudo()

    model = Model.search([('model', '=', 'employee.details')], limit=1)
    if not model:
        return

    existing = Fields.search([('model_id', '=', model.id), ('name', '=', 'partner_id')], limit=1)
    if existing:
        return

    Fields.create({
        'name': 'partner_id',
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
