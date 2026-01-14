from odoo import fields, models

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    # Club on policy (generic res.partner)
    x_club_id = fields.Many2one("res.partner", string="Club", index=True)

    document_count = fields.Integer(string="Documents", compute="_compute_document_count")

    def _compute_document_count(self):
        Doc = self.env["insurance.document"]
        for rec in self:
            rec.document_count = Doc.search_count([("policy_id", "=", rec.id)])

    def action_open_policy_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Documents",
            "res_model": "insurance.document",
            "view_mode": "kanban,list,form",
            "domain": [("policy_id", "=", self.id)],
            "context": {
                "default_policy_id": self.id,
                "default_club_id": self.x_club_id.id or False,
            },
        }
