# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestVNZ16MappingSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Company = cls.env['res.company'].sudo()
        cls.Mapping = cls.env['akahu.company.mapping']
        cls.Engine = cls.env['auto.reconciliation.engine']
        cls.Wizard = cls.env['auto.reconciliation.wizard']
        cls.WizardLine = cls.env['auto.reconciliation.wizard.line']
        cls.Partner = cls.env['res.partner'].sudo()

        cls.company_a = cls.env.company
        cls.company_b = cls.Company.create({'name': 'VNZ16 Company B'})

        cls.partner_ic = cls.Partner.create({'name': 'IC Partner B'})

    def test_create_rejects_disallowed_counterpart_company(self):
        with self.assertRaises(ValidationError):
            self.Mapping.with_context(
                allowed_company_ids=[self.company_a.id]
            ).create({
                'company_id': self.company_a.id,
                'partner_id': self.partner_ic.id,
                'counterpart_company_id': self.company_b.id,
            })

    def test_write_rejects_disallowed_counterpart_company(self):
        mapping = self.Mapping.with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]
        ).create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })

        with self.assertRaises(ValidationError):
            mapping.with_context(
                allowed_company_ids=[self.company_a.id]
            ).write({'notes': 'Trigger security re-check'})

    def test_action_confirm_rejects_disallowed_counterpart_company(self):
        mapping = self.Mapping.with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]
        ).create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })

        with self.assertRaises(ValidationError):
            mapping.with_context(
                allowed_company_ids=[self.company_a.id]
            ).action_confirm()

    def test_engine_rejects_invalid_mapping_runtime_scope(self):
        self.Mapping.with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]
        ).create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })

        with self.assertRaises(ValidationError):
            self.Engine.with_context(
                allowed_company_ids=[self.company_a.id]
            )._reconcile_intercompany(
                self.company_a,
                preview_mode=True,
                allowed_company_ids=[self.company_a.id],
            )

    def test_runtime_security_rejects_wrong_partner_in_mapping_chain(self):
        mapping = self.Mapping.with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]
        ).create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })
        other_partner = self.Partner.create({'name': 'IC Partner C'})

        with self.assertRaises(ValidationError):
            mapping._assert_runtime_security(
                allowed_company_ids=[self.company_a.id, self.company_b.id],
                expected_company_id=self.company_a.id,
                expected_partner_id=other_partner.id,
                expected_counterpart_company_id=self.company_b.id,
            )

    def test_runtime_security_rejects_wrong_counterpart_in_mapping_chain(self):
        mapping = self.Mapping.with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]
        ).create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })

        with self.assertRaises(ValidationError):
            mapping._assert_runtime_security(
                allowed_company_ids=[self.company_a.id, self.company_b.id],
                expected_company_id=self.company_a.id,
                expected_partner_id=self.partner_ic.id,
                expected_counterpart_company_id=self.company_a.id,
            )

    def test_wizard_confirm_rejects_tampered_intercompany_pair(self):
        wizard = self.Wizard.create({
            'company_id': self.company_a.id,
            'match_pairs_json': '[{"type": "intercompany", "line_id": 99999991, "counterpart_line_id": 99999992}]',
        })
        self.WizardLine.create({
            'wizard_id': wizard.id,
            'selected': True,
            'initial_selected': True,
            'pair_index': 0,
            'reconciliation_type': 'intercompany',
            'description': 'Tampered pair',
            'partner_name': 'Unknown',
            'amount': 0.0,
            'match_criteria': 'amount',
        })

        with self.assertRaises(ValidationError):
            wizard.action_confirm()
