# -*- coding: utf-8 -*-
from odoo import fields, models


class UnlinkExistingContactsWizard(models.TransientModel):
    _name = "unlink.existing.contacts.wizard"
    _description = "Unlink Contacts from a Parent Contact"

    company_id = fields.Many2one(
        "res.partner",
        string="Parent Contact",
        required=True,
        readonly=True,
    )

    # Only contacts currently linked under this parent can be selected.
    partner_ids = fields.Many2many(
        "res.partner",
        string="Linked Contacts",
        domain="[('parent_id', '=', company_id)]",
        help="Select linked contacts to detach from this parent. "
             "This clears their parent_id; the contacts themselves are not deleted.",
    )

    def action_unlink(self):
        self.ensure_one()
        if self.partner_ids:
            # Safety: only touch contacts that are really children of this parent.
            to_unlink = self.partner_ids.filtered(
                lambda p: p.parent_id == self.company_id
            )
            to_unlink.write({"parent_id": False})
        return {"type": "ir.actions.act_window_close"}
