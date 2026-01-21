# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SelectFieldConfigWizard(models.TransientModel):
    _inherit = 'select.field.config.wizard'

    # The config is stored on form.builder.field; wizard just edits it.
    is_dynamic_options = fields.Boolean(string='Dynamic Options (DB)', default=False)
    dynamic_model_id = fields.Many2one('ir.model', string='Source Model')
    dynamic_domain = fields.Char(string='Domain', help='Odoo domain, e.g. [("active", "=", True)]')
    dynamic_label_field_id = fields.Many2one('ir.model.fields', string='Label Field',
                                            domain="[('model_id','=',dynamic_model_id),('ttype','in',('char','text','integer','float','selection'))]")
    dynamic_value_field_id = fields.Many2one('ir.model.fields', string='Value Field',
                                            domain="[('model_id','=',dynamic_model_id),('ttype','in',('id','integer','char'))]")
    dynamic_limit = fields.Integer(string='Limit', default=200)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'is_dynamic_options': bool(field.is_dynamic_options),
                'dynamic_model_id': field.dynamic_model_id.id,
                'dynamic_domain': field.dynamic_domain,
                'dynamic_label_field_id': field.dynamic_label_field_id.id,
                'dynamic_value_field_id': field.dynamic_value_field_id.id,
                'dynamic_limit': field.dynamic_limit or 200,
            })
        return defaults

    def action_save_select_config(self):
        # keep upstream behavior (manual option_values + hover text)
        res = super().action_save_select_config()
        self.field_id.write({
            'is_dynamic_options': self.is_dynamic_options,
            'dynamic_model_id': self.dynamic_model_id.id,
            'dynamic_domain': self.dynamic_domain,
            'dynamic_label_field_id': self.dynamic_label_field_id.id,
            'dynamic_value_field_id': self.dynamic_value_field_id.id,
            'dynamic_limit': self.dynamic_limit,
        })
        return res
