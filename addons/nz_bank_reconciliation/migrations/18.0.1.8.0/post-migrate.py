# -*- coding: utf-8 -*-
"""
Migration 18.0.1.8.0 — add durable recovery coverage checkpoint.

The new recovery_covered_through field is intentionally left NULL for existing
rows because historical runs do not provide enough evidence to reconstruct a
safe covered-through boundary.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    _logger.info(
        'Migration 18.0.1.8.0: recovery_covered_through will initialize on the next successful recovery run.'
    )