# -*- coding: utf-8 -*-
"""Zentech Form Dynamic Sources (Odoo 18)

This is an extension addon that adds a rule-based dynamic source resolver to an
existing Zentech Form Builder, without modifying the original module.

How it works:
- Adds a technical key field `code` on `zentech.form.field` (merged if already present).
- When a field's `code` (preferred) OR its label/name matches a known key, it auto-fills:
    * field_type = many2one
    * relation_model = target model (e.g., hr.job)
    * relation_domain (JSON string)
    * relation_label_field (defaults to "name")
- It will NOT overwrite values if `relation_model` is already set explicitly.

Edit FIELD_SOURCE_MAP / LABEL_ALIASES to add more mappings in future.
"""

from odoo import api, fields, models

# ---- Editable mapping (add more in future) ----
FIELD_SOURCE_MAP = {
    # Preferred stable key:
    "volunteer_type": {
        "field_type": "many2one",
        "relation_model": "hr.job",
        "relation_domain": "[]",
        "relation_label_field": "name",
    },
    # Add more like:
    # "department": {"field_type":"many2one","relation_model":"hr.department","relation_domain":"[]","relation_label_field":"name"},
}

# Optional label aliases (if users set label and don't set code)
LABEL_ALIASES = {
    "volunteer type": "volunteer_type",
    "volunteer_type": "volunteer_type",
    "volunteer-type": "volunteer_type",
}

def _norm(s):
    return (s or "").strip().lower()

class ZentechFormFieldExt(models.Model):
    _inherit = "zentech.form.field"

    # Stable technical key for rules. If base module already defines it, Odoo merges.
    code = fields.Char(
        string="Field Code",
        help="Stable technical key (e.g., volunteer_type). Used for auto source mapping."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._apply_source_map_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        # If code/label/name/field_type changes, re-apply (safely)
        if any(k in vals for k in ("code", "label", "name", "field_type")):
            self._apply_source_map_vals(vals)
        return super().write(vals)

    # ---------- Internal ----------
    def _apply_source_map_vals(self, vals):
        """Apply source mapping to vals in-place.

        Works even if the base module uses 'name' instead of 'label'.
        Only applies if mapping key is matched AND target relation fields exist.
        """
        # Determine key preference: code > label/name
        code_key = _norm(vals.get("code"))

        label_val = None
        if "label" in vals:
            label_val = vals.get("label")
        elif "name" in vals:
            label_val = vals.get("name")

        label_key = _norm(label_val)

        key = code_key or LABEL_ALIASES.get(label_key, "")
        if not key:
            return

        cfg = FIELD_SOURCE_MAP.get(key)
        if not cfg:
            return

        # Only apply if the base module has these fields
        required_fields = {"field_type", "relation_model", "relation_domain", "relation_label_field"}
        if not required_fields.issubset(set(self._fields.keys())):
            return

        # Do not overwrite if user/base already set relation_model explicitly
        if vals.get("relation_model"):
            return

        # Set defaults if missing
        for k, v in cfg.items():
            vals.setdefault(k, v)
