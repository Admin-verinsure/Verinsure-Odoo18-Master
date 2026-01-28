# Insurance Policy-first Invoice (POC) - Odoo 18

This module creates **policy.details**, **insurance.details**, and an **invoice (account.move)** from a stored JSON payload.

## Confirmed Model Mapping (your DB)
- Policy: `policy.details`
- Policy Type: `policy.type`
- Insurance: `insurance.details`
- Agent: `employee.details` (`phone` must be exactly 10 digits)
- Invoice link: `account.move.insurance_id` already exists and points to `insurance.details`

## Install
1. Copy folder `insurance_policy_invoice_poc` into your custom addons path.
2. Restart Odoo.
3. Apps → Update Apps List → install module.

## Usage (Odoo shell)
Create a payload record in `invoice.poc.payload` then run:
`rec.action_create_policy_and_invoice()`
