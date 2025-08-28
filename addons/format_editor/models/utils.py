from odoo import models

class ReportUtils(models.AbstractModel):
    _name = "report.utils"   # short + generic
    _description = "Report Helper Utilities"

    def clean_text(self, text):
        """Remove unwanted special characters from narration text"""
        if not text:
            return ""
        return (
            text.replace(u"\xa0", " ")   # replace non-breaking space
                .replace("&nbsp;", " ")  # replace HTML entity
                .strip()
        )
