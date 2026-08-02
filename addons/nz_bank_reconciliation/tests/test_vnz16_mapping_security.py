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
        cls.Partner = cls.env['res.partner'].sudo()
        cls.Users = cls.env['res.users'].sudo().with_context(no_reset_password=True)

        cls.company_a = cls.env.company
        cls.company_b = cls.Company.create({'name': 'VNZ16 Company B'})
        cls.company_c = cls.Company.create({'name': 'VNZ16 Company C'})

        cls.partner_ic = cls.Partner.create({'name': 'IC Partner B'})
        cls.partner_ic_2 = cls.Partner.create({'name': 'IC Partner C'})

        manager_group = cls.env.ref('account.group_account_manager')
        cls.non_admin_manager = cls.Users.create({
            'name': 'VNZ16 Non Admin Manager',
            'login': 'vnz16_non_admin_manager',
            'email': 'vnz16_non_admin_manager@example.com',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id, cls.company_b.id])],
            'groups_id': [(6, 0, [manager_group.id])],
        })
        cls.limited_manager = cls.Users.create({
            'name': 'VNZ16 Limited Manager',
            'login': 'vnz16_limited_manager',
            'email': 'vnz16_limited_manager@example.com',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id])],
            'groups_id': [(6, 0, [manager_group.id])],
        })

    def _create_mapping(self):
        return self.Mapping.create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })

    def test_create_works(self):
        mapping = self._create_mapping()
        self.assertTrue(mapping.exists())
        self.assertEqual(mapping.company_id.id, self.company_a.id)
        self.assertEqual(mapping.partner_id.id, self.partner_ic.id)
        self.assertEqual(mapping.counterpart_company_id.id, self.company_b.id)

    def test_create_succeeds_with_authorized_companies(self):
        mapping = self.Mapping.with_user(self.non_admin_manager).create({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })
        self.assertTrue(mapping.exists())

    def test_create_rejects_unauthorized_company_id(self):
        with self.assertRaisesRegex(
            ValidationError,
            'You are not allowed to create mappings for company id',
        ):
            self.Mapping.with_user(self.limited_manager).create({
                'company_id': self.company_b.id,
                'partner_id': self.partner_ic.id,
                'counterpart_company_id': self.company_a.id,
            })

    def test_create_rejects_unauthorized_counterpart_company_id(self):
        with self.assertRaisesRegex(
            ValidationError,
            'You are not allowed to use counterpart company id',
        ):
            self.Mapping.with_user(self.limited_manager).create({
                'company_id': self.company_a.id,
                'partner_id': self.partner_ic.id,
                'counterpart_company_id': self.company_b.id,
            })

    def test_create_rejects_same_company_and_counterpart(self):
        with self.assertRaisesRegex(
            ValidationError,
            'This Company and Counterpart Company must be different.',
        ):
            self.Mapping.with_user(self.non_admin_manager).create({
                'company_id': self.company_a.id,
                'partner_id': self.partner_ic.id,
                'counterpart_company_id': self.company_a.id,
            })

    def test_notes_can_be_updated(self):
        mapping = self._create_mapping()
        mapping.write({'notes': 'Updated notes'})
        self.assertEqual(mapping.notes, 'Updated notes')

    def test_active_can_be_updated(self):
        mapping = self._create_mapping()
        mapping.write({'active': False})
        self.assertFalse(mapping.active)

    def test_company_id_update_fails(self):
        mapping = self._create_mapping()
        with self.assertRaisesRegex(
            ValidationError,
            'Inter-company mappings cannot be modified after creation. Create a new mapping instead.',
        ):
            mapping.write({'company_id': self.company_b.id})

    def test_partner_id_update_fails(self):
        mapping = self._create_mapping()
        with self.assertRaisesRegex(
            ValidationError,
            'Inter-company mappings cannot be modified after creation. Create a new mapping instead.',
        ):
            mapping.write({'partner_id': self.partner_ic_2.id})

    def test_counterpart_company_id_update_fails(self):
        mapping = self._create_mapping()
        with self.assertRaisesRegex(
            ValidationError,
            'Inter-company mappings cannot be modified after creation. Create a new mapping instead.',
        ):
            mapping.write({'counterpart_company_id': self.company_a.id})

    def test_multi_record_write_protected_field_fails(self):
        mapping_1 = self._create_mapping()
        mapping_2 = self.Mapping.create({
            'company_id': self.company_b.id,
            'partner_id': self.partner_ic_2.id,
            'counterpart_company_id': self.company_a.id,
        })

        with self.assertRaisesRegex(
            ValidationError,
            'Inter-company mappings cannot be modified after creation. Create a new mapping instead.',
        ):
            (mapping_1 | mapping_2).write({'partner_id': self.partner_ic.id})

    def test_administrator_can_delete_mapping(self):
        mapping = self._create_mapping()
        mapping.unlink()
        self.assertFalse(mapping.exists())

    def test_normal_user_cannot_delete_mapping(self):
        mapping = self._create_mapping()
        with self.assertRaisesRegex(
            ValidationError,
            'Only System Administrators can delete inter-company mappings.',
        ):
            mapping.with_user(self.non_admin_manager).unlink()

    def test_runtime_security_passes_on_valid_mapping(self):
        mapping = self._create_mapping()
        self.assertTrue(mapping._assert_runtime_security())

    def test_runtime_security_missing_company_raises(self):
        malformed = self.Mapping.new({
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_b.id,
        })
        with self.assertRaises(ValidationError):
            malformed._assert_runtime_security()

    def test_runtime_security_missing_partner_raises(self):
        malformed = self.Mapping.new({
            'company_id': self.company_a.id,
            'counterpart_company_id': self.company_b.id,
        })
        with self.assertRaises(ValidationError):
            malformed._assert_runtime_security()

    def test_runtime_security_missing_counterpart_raises(self):
        malformed = self.Mapping.new({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
        })
        with self.assertRaises(ValidationError):
            malformed._assert_runtime_security()

    def test_runtime_security_same_company_and_counterpart_raises(self):
        malformed = self.Mapping.new({
            'company_id': self.company_a.id,
            'partner_id': self.partner_ic.id,
            'counterpart_company_id': self.company_a.id,
        })
        with self.assertRaises(ValidationError):
            malformed._assert_runtime_security()
