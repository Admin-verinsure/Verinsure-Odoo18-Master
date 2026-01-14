{
  "name": "Insurance Documents",
  "version": "18.0.1.0.9",
  "category": "Insurance",
  "summary": "Insurance documents with club-wise visibility (safe, no global attachment rules)",
  "depends": ["base", "mail", "insurance_management_cybro"],
  "data": [
    "security/security.xml",
    "security/ir.model.access.csv",
    "views/insurance_document_views.xml",
    "views/insurance_details_views.xml",
    "views/res_users_views.xml"
  ],
  "installable": true,
  "application": false
}