Form Builder – Dynamic Dropdowns & Branching (Odoo 18)
=====================================================

This addon extends the existing **zehntech_form_builder** module with:

1) Dynamic dropdown/radio/checkbox options loaded from any Odoo model (ex: Clubs)
2) Branching rules to route users to a different shared form based on answers

Install
-------
- Install ``zehntech_form_builder`` first
- Install this addon ``zt_form_builder_dynamic``

Usage
-----
Dynamic dropdown:
- Edit a field (Select/Radio/Checkbox)
- Enable **Dynamic Options (DB)**
- Choose Source Model, Label Field, Value Field, Domain (optional)

Branching:
- Go to Form Builder -> Branch Rules
- Create rules for a source form:
  - Trigger Field
  - Operator + value
  - Target Form
  - Optional fallback form

Notes
-----
- For public forms, keep domains simple and avoid exposing sensitive models.
