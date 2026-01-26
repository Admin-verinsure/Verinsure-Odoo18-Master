import json
from odoo import models, fields, api


class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"
    _order = "create_date asc"

    # --------------------------------------------------
    # CORE FIELDS
    # --------------------------------------------------
    form_id = fields.Many2one("smart.form", required=True)
    partner_id = fields.Many2one("res.partner")

    first_name = fields.Char()
    last_name = fields.Char()
    email = fields.Char()
    phone = fields.Char()

    data_source = fields.Selection(
        [
            ("partner", "Fetched from Partner"),
            ("form", "Submitted via Form"),
        ]
    )

    data_json = fields.Text(string="Raw Data")
    readable_text = fields.Text(string="Readable Data")  # ✅ FINAL FIX

    ip = fields.Char()
    user_agent = fields.Char()

    # --------------------------------------------------
    # CREATE / WRITE
    # --------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._build_readable_text()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "data_json" in vals or "form_id" in vals:
            self._build_readable_text()
        return res

    # --------------------------------------------------
    # BUILD READABLE DATA
    # --------------------------------------------------
    def _build_readable_text(self):
        for rec in self:
            if not rec.data_json or not rec.form_id:
                rec.readable_text = ""
                continue

            try:
                submitted = json.loads(rec.data_json)
            except Exception:
                submitted = {}

            lines = []

            label_map = {}
            for field in rec.form_id.sudo().field_ids:
                key = field.name or f"field_{field.id}"
                label_map[key] = field.label or field.name or key

            for key, value in submitted.items():
                label = label_map.get(key, key)

                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value if v)

                lines.append(f"{label}: {value}")

            rec.readable_text = "\n".join(lines)
