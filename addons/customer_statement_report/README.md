# Customer Statement Report — Odoo 18 Custom Module

## Overview
A fully dynamic customer statement report module for Odoo 18. Generates professional
account statements per customer with aging analysis, balance summaries, and PDF export.

---

## Features

| Feature | Details |
|---|---|
| **Action Menu Integration** | Appears under *Action* button in Customers list & form view |
| **Multi-Customer** | Generate statements for one or many customers at once |
| **Date Range Filter** | Custom from/to dates |
| **Journal Filter** | Filter by specific accounting journals |
| **Currency Support** | Works with any configured currency |
| **Statement Types** | Detailed / Summary / Outstanding Items Only |
| **Opening Balance** | Shows pre-period balance |
| **Aging Analysis** | Configurable buckets (30/60/90/120 days default) |
| **PDF Export** | Professional A4 PDF with company header |
| **Reconciliation Filter** | Show only unreconciled items |

---

## Installation

1. Copy the `customer_statement_report` folder to your Odoo addons path:
   ```
   /your-odoo/addons/customer_statement_report/
   ```

2. Restart the Odoo server:
   ```bash
   sudo systemctl restart odoo
   # or
   ./odoo-bin -c odoo.conf
   ```

3. Activate developer mode in Odoo settings.

4. Go to **Apps → Update Apps List**, then search for **"Customer Statement Report"** and install it.

---

## Usage

### From Customers List View
1. Go to **Accounting → Customers** (or **Contacts → Customers**)
2. Select one or more customers (optional)
3. Click the **⚙ Action** dropdown menu
4. Select **"Print Customer Statement"**
5. Configure filters in the wizard dialog
6. Click **Print PDF** or **Preview**

### Wizard Options Explained

| Field | Description |
|---|---|
| **Date From / Date To** | Transaction period for the statement |
| **Customers** | Leave empty = all customers; select specific ones to filter |
| **Company** | Multi-company support |
| **Currency** | Statement currency (defaults to company currency) |
| **Statement Type** | Detailed (all lines) / Summary (totals only) / Outstanding (unpaid only) |
| **Include Unreconciled Only** | Only show entries not fully matched/paid |
| **Show Opening Balance** | Include pre-period balance row |
| **Show Aging Analysis** | Append aging bucket table at bottom |
| **Journal Filter** | Limit to specific journals (sales, bank, cash, etc.) |
| **Aging Buckets** | Days thresholds for aging columns |

---

## Module Structure

```
customer_statement_report/
├── __manifest__.py              # Module metadata
├── __init__.py
├── security/
│   └── ir.model.access.csv     # Access rights (user/manager/invoice)
├── wizard/
│   ├── __init__.py
│   ├── customer_statement_wizard.py    # Core logic & data computation
│   └── customer_statement_wizard_views.xml  # Wizard dialog UI
├── report/
│   ├── customer_statement_report.xml          # Report action registration
│   └── customer_statement_report_template.xml # QWeb PDF template
├── views/
│   └── res_partner_views.xml   # Binds action to Customers menu
└── static/src/css/
    ├── customer_statement.css  # Backend wizard styles
    └── report_style.css        # PDF report styles
```

---

## Report Sections (PDF Output)

1. **Company Header** — auto-inserted by Odoo's external layout
2. **Statement Header** — period, customer address, VAT, contact info
3. **Summary Boxes** — Opening balance / Total invoiced / Total payments / Closing balance
4. **Transaction Table** — Date, Reference, Description, Journal, Due Date, Debit, Credit, Running Balance
5. **Aging Analysis** — Current / 1-30 / 31-60 / 61-90 / 90+ days buckets
6. **Footer** — Generation timestamp + Amount Due highlight box

---

## Compatibility

- ✅ Odoo 18.0 Community & Enterprise
- ✅ Multi-company
- ✅ Multi-currency
- ✅ Access control: Account User / Invoice / Manager roles

---

## Troubleshooting

**Action menu not showing?**
- Make sure the module is installed and the server was restarted
- Clear browser cache and refresh

**PDF shows no data?**
- Confirm customers have posted journal entries in the selected period
- Check that the account type is `asset_receivable`

**Permission denied error?**
- The user must belong to at least one of: `account.group_account_user`, `account.group_account_invoice`, or `account.group_account_manager`
