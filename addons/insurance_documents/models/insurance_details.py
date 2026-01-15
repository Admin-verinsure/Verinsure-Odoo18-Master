from odoo import fields, models

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    # Compatibility fields: use document_count in views (common name)
    document_count = fields.Integer(string="Documents", compute="_compute_dms_doc_count")
    dms_doc_count = fields.Integer(string="Documents (DMS)", compute="_compute_dms_doc_count")

    def _compute_dms_doc_count(self):
        DmsFile = self.env["dms.file"]
        for rec in self:
            cnt = DmsFile.search_count([
                ("res_model", "=", rec._name),
                ("res_id", "=", rec.id),
            ])
            rec.document_count = cnt
            rec.dms_doc_count = cnt

    def action_open_dms_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Policy Documents",
            "res_model": "dms.file",
            "view_mode": "kanban,list,form",
            "domain": [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
            ],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_directory_id": 51,
            },
        }
