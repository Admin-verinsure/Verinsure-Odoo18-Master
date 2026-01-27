from odoo import api, fields, models
import secrets

class SmartForm(models.Model):
    _name = "smart.form"
    _description = "Smart Form"
    _order = "id desc"

    name = fields.Char(required=True)
    token = fields.Char(index=True, readonly=True, copy=False, default=lambda self: secrets.token_urlsafe(16))
    active = fields.Boolean(default=True)

    # Optional: store submissions into an Odoo model record
    store_in_model = fields.Boolean(string="Store in Database Model", default=False)
    target_model_id = fields.Many2one("ir.model", string="Target Model", ondelete="restrict")
    field_mapping_ids = fields.One2many("smart.form.model.map", "form_id", string="Field Mapping", copy=True)

    field_ids = fields.One2many("smart.form.field", "form_id", string="Fields", copy=True)
    submission_ids = fields.One2many("smart.form.submission", "form_id", string="Submissions", readonly=True)
    branch_rule_ids = fields.One2many("smart.form.branch.rule", "form_id", string="Branch Rules", copy=True)
    logic_rule_ids = fields.One2many("smart.form.logic.rule", "form_id", string="Logic Rules", copy=True)

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
    """Build create() vals for the configured target model from answers_by_id.

    answers_by_id keys are string(field_id). Values are either:
      - scalar (text/number/etc)
      - list (checkbox values)
      - dict {"value": ..., "label": ...} for select/radio
    Only mapped fields are written; anything unmapped is skipped.
    """
    self.ensure_one()
    vals = {}
    for m in self.field_mapping_ids.sorted(lambda r: (r.sequence, r.id)):
        ff = m.form_field_id
        mf = m.model_field_id
        if not ff or not mf:
            continue

        raw = answers_by_id.get(str(ff.id))
        if raw in (None, "", [], {}):
            continue

        # unwrap dict answers for select/radio
        if isinstance(raw, dict):
            value = raw.get("value")
            label = raw.get("label")
        else:
            value = raw
            label = None

        if value in (None, "", [], {}):
            continue

        t = mf.ttype

        try:
            if t in ("char", "text", "html"):
                vals[mf.name] = str(label or value)

            elif t == "boolean":
                if isinstance(value, str):
                    vals[mf.name] = value.strip().lower() in ("1", "true", "yes", "y", "on")
                else:
                    vals[mf.name] = bool(value)

            elif t == "integer":
                vals[mf.name] = int(value)

            elif t in ("float", "monetary"):
                vals[mf.name] = float(value)

            elif t in ("date", "datetime"):
                # Expect ISO string from frontend; if invalid, let create() raise
                vals[mf.name] = value

            elif t == "selection":
                # Prefer value (selection key). If user mapped label by mistake,
                # keep it as-is; create() will raise if invalid.
                vals[mf.name] = str(value)

            elif t == "many2one":
                # Prefer numeric id; else try name search (best-effort)
                if isinstance(value, int):
                    vals[mf.name] = value
                elif isinstance(value, str) and value.isdigit():
                    vals[mf.name] = int(value)
                else:
                    # Best-effort by name (can be ambiguous)
                    rec = self.env[mf.relation].sudo().search([("name", "=", str(label or value))], limit=1)
                    if rec:
                        vals[mf.name] = rec.id

            elif t in ("many2many", "one2many"):
                # Expect list of ids
                ids = value if isinstance(value, list) else []
                ids = [int(x) for x in ids if str(x).isdigit()]
                vals[mf.name] = [(6, 0, ids)]

            else:
                # Fallback: try plain assignment
                vals[mf.name] = value
        except Exception:
            # Skip any unmappable value silently as requested
            continue

    return vals
