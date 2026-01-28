# Insurance Policy-first Invoice (POC) - Odoo 18 (NO XML)

This build ships no XML due to strict RelaxNG validation on your server.

Agent mapping:
- employee.details has no email field
- we search/create by phone
- we optionally link user_id if res.users with matching login/email exists

Models used:
- policy.details, policy.type, insurance.details, employee.details, account.move.insurance_id
