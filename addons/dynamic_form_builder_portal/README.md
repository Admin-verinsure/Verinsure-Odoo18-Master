Dynamic Form Builder (Portal) - Odoo 18
======================================

What you get
------------
- Backend app to build form templates with multi-step sections.
- Question types: text, long text, date, number, yes/no, selection, multiselect, signature, file.
- Conditional visibility using structured rules (depends on other question + operator + value).
- Portal pages:
  - /my/forms (start new, list existing)
  - /my/forms/<id> (fill + autosave)
- Sensitive sections: store answers separately with stricter access control.

Notes
-----
- Autosave uses JSON-RPC (Odoo 18 JS @odoo-module) and works for most field types.
- File upload route can be added (kept minimal here for stability).

Install
-------
1) Copy addon folder to your custom addons path.
2) Update Apps list, install "Dynamic Form Builder (Portal)".
3) Give internal users the group "Dynamic Forms: Manager" to design templates.
