# -*- coding: utf-8 -*-
from odoo import models

class ResPartner(models.Model):
    _inherit = "res.partner"

    def name_get(self):
        """Show only person name for child contacts.

        If a partner is a PERSON linked to a parent company (parent_id),
        return only the person's own name instead of 'Company, Person'.

        NOTE: This is a GLOBAL change (dropdowns, search, etc.).
        """
        res = super().name_get()
        by_id = dict(res)

        for p in self:
            if p.parent_id and not p.is_company:
                by_id[p.id] = p.name or by_id.get(p.id) or ""

        return [(pid, by_id[pid]) for pid, _ in res]
