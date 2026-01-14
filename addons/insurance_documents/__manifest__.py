{
  "name": "Insurance Documents",
  "version": "18.0.1.1.0",
  "category": "Insurance",
  "summary": "Safe club/user document visibility without touching global attachments",
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