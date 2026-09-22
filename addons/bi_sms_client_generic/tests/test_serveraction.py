from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBiSmsServerAction(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Users = cls.env['res.users'].sudo().with_context(no_reset_password=True)
        cls.ServerAction = cls.env['ir.actions.server']
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.server_action_model = cls.env['ir.model']._get('ir.actions.server')
        internal_group = cls.env.ref('base.group_user')
        cls.internal_user = cls.Users.create({
            'name': 'BI SMS Internal User',
            'login': 'bi_sms_internal_user',
            'email': 'bi_sms_internal_user@example.com',
            'company_id': cls.env.company.id,
            'company_ids': [(6, 0, cls.env.company.ids)],
            'groups_id': [(6, 0, [internal_group.id])],
        })

    def test_code_action_runs_without_server_action_read_access(self):
        action = self.ServerAction.sudo().create({
            'name': 'Code Action ACL Compatibility',
            'model_id': self.partner_model.id,
            'state': 'code',
            'code': "action = {'type': 'ir.actions.act_window_close'}",
        })

        with self.assertRaises(AccessError):
            action.with_user(self.internal_user).read(['name'])

        result = action.with_user(self.internal_user).with_context(
            active_model='res.partner',
        ).run()

        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})

    def test_sms_action_uses_sms_branch(self):
        action = self.ServerAction.sudo().create({
            'name': 'SMS Action Branch',
            'model_id': self.partner_model.id,
            'state': 'sms',
            'condition': 'True',
        })

        with patch.object(type(self.ServerAction), '_run_sms_action', autospec=True, return_value='sms-result') as run_sms_action:
            result = action.with_user(self.internal_user).with_context(
                active_model='res.partner',
            ).run()

        self.assertEqual(result, 'sms-result')
        self.assertEqual(run_sms_action.call_count, 1)
        self.assertEqual(run_sms_action.call_args.args[0].id, action.id)
        self.assertEqual(run_sms_action.call_args.args[1].id, action.id)

    def test_code_action_keeps_native_model_access_checks(self):
        action = self.ServerAction.sudo().create({
            'name': 'Code Action Native Security',
            'model_id': self.server_action_model.id,
            'state': 'code',
            'code': 'action = False',
        })

        with self.assertRaises(AccessError):
            action.with_user(self.internal_user).with_context(
                active_model='ir.actions.server',
            ).run()
