from odoo import fields, models

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    x_club_id = fields.Many2one("res.partner", string="Club", index=True)

    attachment_count = fields.Integer(string="Documents", compute="_compute_attachment_count")

    def _compute_attachment_count(self):
        Attachment = self.env["ir.attachment"]
        for rec in self:
            rec.attachment_count = Attachment.search_count([
                ("res_model", "=", rec._name),
                ("res_id", "=", rec.id),
                ("x_insurance_doc", "=", True),
            ])

    def action_open_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Documents",
            "res_model": "ir.attachment",
            "view_mode": "kanban,list,form",
            "domain": [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("x_insurance_doc", "=", True),
            ],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_x_insurance_doc": True,
            },
        }
