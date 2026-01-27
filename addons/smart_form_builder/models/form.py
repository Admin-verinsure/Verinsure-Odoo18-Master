from odoo import api, fields, models
import secrets

class SmartForm(models.Model):
    _name = "smart.form"
    _description = "Smart Form"
    _order = "id desc"

    name = fields.Char(required=True)
    token = fields.Char(index=True, readonly=True, copy=False, default=lambda self: secrets.token_urlsafe(16))
    active = fields.Boolean(default=True)

    field_ids = fields.One2many("smart.form.field", "form_id", string="Fields", copy=True)
    submission_ids = fields.One2many("smart.form.submission", "form_id", string="Submissions", readonly=True)
    branch_rule_ids = fields.One2many("smart.form.branch.rule", "form_id", string="Branch Rules", copy=True)
    logic_rule_ids = fields.One2many("smart.form.logic.rule", "form_id", string="Logic Rules", copy=True)

    # Optional: store submissions into a configured Odoo model (e.g., Contacts/res.partner)
    store_in_model = fields.Boolean(string="Store in Database Model", default=False)
    target_model_id = fields.Many2one("ir.model", string="Target Model", ondelete="restrict")
    model_field_mapping_ids = fields.One2many("smart.form.model.map", "form_id", string="Field Mapping")

    submission_count = fields.Integer(compute="_compute_submission_count")

    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    def action_open_public(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}",
            "target": "new",
        }

    def action_open_preview(self):
        # Preview is same as public but with ?preview=1
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}?preview=1",
            "target": "new",
        }

    def action_view_submissions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Submissions",
            "res_model": "smart.form.submission",
            "view_mode": "list,form",
            "domain": [("form_id", "=", self.id)],
            "context": {"default_form_id": self.id},
        }


    def _build_target_record_vals(self, answers_by_id):
        """Build vals for the configured target model based on mapping.

        - Unmapped fields are ignored (as requested).
        - If store_in_model/target_model_id not configured, returns {}.
        """
        self.ensure_one()
        if not self.store_in_model or not self.target_model_id:
            return {}

        vals = {}
        for m in self.model_field_mapping_ids.sorted(lambda r: (r.sequence, r.id)):
            ff = m.form_field_id
            mf = m.model_field_id
            if not ff or not mf:
                continue

            raw = answers_by_id.get(str(ff.id))
            if raw is None:
                continue

            if isinstance(raw, dict):
                value = raw.get("value")
                label = raw.get("label")
            else:
                value = raw
                label = None

            if value in (None, "", [], {}, False):
                continue

            try:
                t = mf.ttype
                if t in ("char", "text", "html"):
                    # Prefer human label when available
                    vals[mf.name] = str(label if label not in (None, "") else value)

                elif t == "integer":
                    vals[mf.name] = int(value)

                elif t in ("float", "monetary"):
                    vals[mf.name] = float(value)

                elif t == "boolean":
                    if isinstance(value, str):
                        vals[mf.name] = value.strip().lower() in ("1", "true", "yes", "y", "on")
                    else:
                        vals[mf.name] = bool(value)

                elif t in ("date", "datetime"):
                    # Expect ISO strings from the website form; store as-is
                    vals[mf.name] = value

                elif t == "selection":
                    # Selection expects the key; assume your option value stores the key
                    vals[mf.name] = str(value)

                elif t == "many2one":
                    if isinstance(value, (int,)) or (isinstance(value, str) and value.isdigit()):
                        vals[mf.name] = int(value)
                    else:
                        # Best-effort: search by display name
                        rel = self.env[mf.relation]
                        rec = rel.search([("name", "=", str(value))], limit=1)
                        if rec:
                            vals[mf.name] = rec.id

                elif t in ("many2many", "one2many"):
                    ids = value if isinstance(value, list) else []
                    ids = [int(x) for x in ids if str(x).isdigit()]
                    if ids:
                        vals[mf.name] = [(6, 0, ids)]

                # unsupported types are silently ignored
            except Exception:
                # Skip any mapping that can't be converted
                continue

        return vals
