# -*- coding: utf-8 -*-

from odoo import api, SUPERUSER_ID


def post_init_hook(cr, registry):
    """Create missing `partner_id` on `employee.details` if that model exists.

    This avoids registry crashes from Python `_inherit = 'employee.details'` on
    databases where that model isn't installed yet, while still fixing the
    runtime crash you saw when an ir.rule references `partner_id`.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    # If the model doesn't exist in this DB, do nothing.
    if 'employee.details' not in env:
        return

    model = env['ir.model'].sudo().search([('model', '=', 'employee.details')], limit=1)
    if not model:
        return

    Fields = env['ir.model.fields'].sudo()
    existing = Fields.search([
        ('model_id', '=', model.id),
        ('name', '=', 'partner_id'),
    ], limit=1)
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
