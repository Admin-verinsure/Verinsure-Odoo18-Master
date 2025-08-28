from odoo import models

class ReportUtils(models.AbstractModel):
    _name = "report.utils"
    _description = "Report Helper Utilities"

    def clean_text(self, text):
        """Clean narration text for PDF output"""
        if not text:
            return ""

        # Ensure text is unicode, replace non-breaking spaces and similar chars
        cleaned = (
            text.replace(u"\xa0", " ")   # non-breaking space
                .replace(u"\u202f", " ") # narrow non-breaking space
                .replace("&nbsp;", " ")  # HTML entity
                .replace("Â", " ")       # stray UTF-8 artifact
                .strip()
        )
        return cleaned
