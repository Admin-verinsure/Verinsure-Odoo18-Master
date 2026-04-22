# helpdesk_recaptcha – Odoo 18

Protects the **Helpdesk website ticket form** with Google reCAPTCHA v3,
using Odoo 18's built-in recaptcha infrastructure.

---

## Prerequisites

1. Odoo 18 with `website_helpdesk` and `website_recaptcha` installed.
2. reCAPTCHA v3 keys configured in **Settings → Integrations → reCAPTCHA**
   (Site Key + Secret Key + Minimum score).

---

## Installation

```bash
# Copy module to your addons path, then:
./odoo-bin -d YOUR_DB -u helpdesk_recaptcha
# or install via Apps menu (search "Helpdesk reCAPTCHA Protection")
```

---

## Module structure

```
helpdesk_recaptcha/
├── __manifest__.py
├── __init__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                        ← conditional CAPTCHA validation
├── views/
│   └── helpdesk_form_recaptcha.xml    ← inherits helpdesk form
└── static/src/
    ├── js/helpdesk_recaptcha.js       ← error display widget patch
    └── css/helpdesk_recaptcha.css     ← scoped error styles
```

No `models/` directory – keys are owned by `website_recaptcha`.

---

## How it works

```
User fills Helpdesk form
        │
        ▼
Odoo's website_recaptcha JS calls grecaptcha.execute()
        │
        ▼ token injected into hidden g-recaptcha-response field
        │
POST /website/form/helpdesk.ticket
        │
        ▼
HelpdeskWebsiteForm.website_form()
        │
        ├─ model != helpdesk.ticket? ──► super() unchanged (Contact Us etc.)
        │
        ├─ pop g-recaptcha-response from kwargs  (prevent ORM field error)
        │
        ├─ read recaptcha.secret_key from ir.config_parameter
        │
        ├─ POST https://www.google.com/recaptcha/api/siteverify
        │
        ├─ success=false or score < min_score?
        │       │
        │       └─► JSON 400 {captcha_error:true, error:"..."}
        │                   │
        │               JS shows inline error div
        │
        └─► super() → helpdesk.ticket created → redirect
```

---

## Key Odoo 18 compatibility notes

| Topic | Detail |
|-------|--------|
| Controller import | `from odoo.addons.website.controllers.form import WebsiteForm` |
| JSON response | `request.make_json_response(data, status=400)` |
| Route override | `@http.route()` with no args inherits parent route |
| JS module | `/** @odoo-module **/` header (ES module, not `odoo.define`) |
| Widget patch | `publicWidget.registry.WebsiteFormWidget?.include({})` |
| Asset bundle | `web.assets_frontend` in `__manifest__.py` assets dict |
| Native reCAPTCHA | `t-call="website.recaptcha"` in QWeb (no manual script tag) |

---

## Common pitfalls

### `g-recaptcha-response` causes ORM ValueError
**Fix:** `kwargs.pop('g-recaptcha-response', '')` before calling `super()`.

### CAPTCHA applied to all forms
**Fix:** `if model_name != 'helpdesk.ticket': return super(...)` as first line.

### Conflict with Odoo signup CAPTCHA
**Fix:** Use `t-call="website.recaptcha"` — Odoo's native template handles
deduplication of the script tag.

### JS import path wrong in Odoo 18
**Fix:** Use `@web/legacy/js/public/public_widget` not `web.public.widget`.

### Keys stored in wrong config param
**Fix:** Read `recaptcha.secret_key` (Odoo's own key), not a custom one.
