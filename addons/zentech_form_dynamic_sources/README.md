# Zentech Form Dynamic Sources (Odoo 18)

Extension addon that adds a rule-based dynamic source resolver to your existing
Zentech Form Builder without editing the original module.

## What it does
- Adds `code` on `zentech.form.field`.
- Auto-configures dynamic source when:
  - `code == volunteer_type` OR
  - label/name is "Volunteer Type" (case-insensitive)

Default mapping:
- `volunteer_type` -> `hr.job` (label field: name)

## How to use
1) Install this addon.
2) In your form builder, create a field with label **Volunteer Type**.
   (Optional: set `code` = `volunteer_type` if you later expose it in UI.)
3) Your renderer (OWL/JS) should read `relation_model` etc. and show dropdown options.

## Add future mappings
Edit `models/zentech_form_field_ext.py` and add entries to `FIELD_SOURCE_MAP`
and (optionally) `LABEL_ALIASES`.
