import re
import html
from odoo import models

class ReportUtils(models.AbstractModel):
    _name = "report.utils"
    _description = "Report Helper Utilities"

    def clean_text(self, text):
        """Clean narration text for PDF output"""
        if not text:
            return ""

        # Convert HTML entities (like &nbsp;)
        text = html.unescape(text)

        # Remove stray "Â" and replace non-breaking spaces
        text = text.replace("Â", " ").replace(u"\xa0", " ")

        # Remove *all* non-printable / control characters
        text = re.sub(r"[^\x20-\x7E\n\r]", " ", text)

        # Collapse multiple spaces
        text = re.sub(r"\s+", " ", text).strip()

        return text
