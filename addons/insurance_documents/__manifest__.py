{
    "name": "Insurance Documents",
    "version": "18.0.1.0.5",
    "category": "Insurance",
    "summary": "Upload and manage documents in Insurance module (global + per policy)",
    "depends": ["base", "mail", "insurance_management_cybro"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/insurance_documents_views.xml"
    ],
    "installable": True,
    "application": False
}