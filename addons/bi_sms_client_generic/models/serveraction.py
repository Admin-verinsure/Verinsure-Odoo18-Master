# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#    Copyright (C) 2013 Julius Network Solutions SARL <contact@julius.fr>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
import time
import logging

_logger = logging.getLogger('smsclient')

class ServerAction(models.Model):
    """
    Possibility to specify the SMS Gateway when configure this server action
    """
    _inherit = 'ir.actions.server'

    action_type = fields.Selection([('sms','SMS')], 'action Type')
    sms =  fields.Char('sms')
    mobile = fields.Char('Mobile')
    condition =  fields.Char('Condition')
    sms_server = fields.Many2one('sms.smsclient', 'SMS Server',
            help='Select the SMS Gateway configuration to use with this action')
    sms_template_id  = fields.Many2one('mail.template', 'SMS Template',
            help='Select the SMS Template configuration to use with this action')


    @api.model
    def run(self):
        res = False
        actions = {action.id: action for action in self}
        for sudo_action in self.sudo():
            action = actions.get(sudo_action.id, self.browse(sudo_action.id))
            if sudo_action.state == 'sms':
                res = action._run_sms_action(sudo_action) or res
                continue
            res = super(ServerAction, action).run() or res
        return res

    def _run_sms_action(self, sudo_action):
        self.ensure_one()

        action_groups = sudo_action.groups_id
        if action_groups:
            if not (action_groups & self.env.user.groups_id):
                raise AccessError(_("You don't have enough access rights to run this action."))
        else:
            model_name = sudo_action.model_id.model
            try:
                self.env[model_name].check_access("write")
            except AccessError:
                _logger.warning(
                    "Forbidden server action %r executed while the user %s does not have access to %s.",
                    sudo_action.name, self.env.user.login, model_name,
                )
                raise

        eval_context = self._get_eval_context(sudo_action)
        records = eval_context.get('record') or eval_context['model']
        records |= eval_context.get('records') or eval_context['model']
        if not action_groups and records.ids:
            try:
                records.check_access('write')
            except AccessError:
                _logger.warning(
                    "Forbidden server action %r executed while the user %s does not have access to %s.",
                    sudo_action.name, self.env.user.login, records,
                )
                raise

        context = self.env.context
        obj_pool = self.env[sudo_action.model_id.model]
        obj = obj_pool.browse(context.get('active_id', False))
        email_template_obj = self.env['mail.template']
        cxt = {
            'context': context,
            'object': obj,
            'time': time,
            'cr': self._cr,
            'pool': self.env,
            'uid': self._uid,
        }
        expr = eval(str(sudo_action.condition), cxt)
        if not expr:
            return False

        _logger.info('Send SMS')
        queue_obj = self.env['sms.smsclient.queue']
        mobile = str(sudo_action.mobile)
        to = None
        try:
            cxt.update({'gateway': sudo_action.sms_server})
            gateway = sudo_action.sms_template_id.gateway_id
            if mobile:
                to = eval(sudo_action.mobile, cxt)
            res_id = context.get('active_id')
            template = email_template_obj.get_email_template(sudo_action.sms_template_id.id, res_id, context)
            values = {}
            for field in ['subject', 'body_html', 'email_from',
                          'email_to', 'email_recipients', 'email_cc', 'reply_to']:
                values[field] = email_template_obj.render_template(
                    getattr(template, field), template.model, res_id, context=context,
                ) or False
            vals = {
                'name': gateway.url,
                'gateway_id': gateway.id,
                'state': 'draft',
                'mobile': to,
                'msg': values['body_html'],
                'validity': gateway.validity,
                'classes': gateway.classes,
                'deferred': gateway.deferred,
                'priority': gateway.priority,
                'coding': gateway.coding,
                'tag': gateway.tag,
                'nostop': gateway.nostop,
            }
            sms_in_q = queue_obj.search([
                ('name', '=', gateway.url),
                ('gateway_id', '=', gateway.id),
                ('state', '=', 'draft'),
                ('mobile', '=', to),
                ('msg', '=', values['body_html']),
                ('validity', '=', gateway.validity),
                ('classes', '=', gateway.classes),
                ('deferred', '=', gateway.deferred),
                ('priority', '=', gateway.priority),
                ('coding', '=', gateway.coding),
                ('tag', '=', gateway.tag),
                ('nostop', '=', gateway.nostop),
            ], limit=1)
            if not sms_in_q:
                queue_obj.create(vals)
                _logger.info('SMS successfully send to : %s' % (to))
        except Exception as e:
            _logger.error('Failed to send SMS : %s' % repr(e))
        return False

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
