import importlib.util
import sys
import types
from datetime import date
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "models" / "invoice_payload.py"


class DummyFields:
    @staticmethod
    def today():
        return date(2024, 1, 1)

    @staticmethod
    def to_date(value):
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        return None


class DummyModel:
    pass


odoo_module = types.ModuleType("odoo")
odoo_module.fields = DummyFields
odoo_module.models = types.SimpleNamespace(Model=DummyModel)
odoo_module._ = lambda msg: msg

exceptions_module = types.ModuleType("odoo.exceptions")


class ValidationError(Exception):
    pass


exceptions_module.ValidationError = ValidationError
sys.modules.setdefault("odoo", odoo_module)
sys.modules.setdefault("odoo.exceptions", exceptions_module)

spec = importlib.util.spec_from_file_location("invoice_payload_test_module", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_get_payload_date_uses_nested_and_fallback_fields():
    handler = module.InvoicePocPayload.__new__(module.InvoicePocPayload)

    payload = {
        "policy": {"start_date": "2024-02-10"},
        "invoice": {"date": "2024-03-15"},
    }

    assert handler._get_payload_date(payload, ("policy", "start_date"), "start_date") == date(2024, 2, 10)
    assert handler._get_payload_date(payload, ("invoice", "date"), "invoice_date") == date(2024, 3, 15)
    assert handler._get_payload_date({"invoice_date": "2024-04-20"}, "date", "invoice_date") == date(2024, 4, 20)


def test_get_payload_date_supports_camel_case_and_alternate_names():
    handler = module.InvoicePocPayload.__new__(module.InvoicePocPayload)

    payload = {
        "policy": {"effectiveDate": "2024-05-01"},
        "insurance": {"expiryDate": "2024-06-15"},
        "invoice": {"invoiceDate": "2024-07-20"},
    }

    assert handler._get_payload_date(payload, ("policy", "start_date")) == date(2024, 5, 1)
    assert handler._get_payload_date(payload, ("insurance", "expiry_date")) == date(2024, 6, 15)
    assert handler._get_payload_date(payload, ("invoice", "invoice_date")) == date(2024, 7, 20)


def test_get_payload_date_supports_nested_dates_object_with_text_fields():
    handler = module.InvoicePocPayload.__new__(module.InvoicePocPayload)

    payload = {
        "dates": {
            "startDateText": "2024-08-01",
            "endDateText": "2024-09-15",
        }
    }

    assert handler._get_payload_date(payload, ("dates", "start_date")) == date(2024, 8, 1)
    assert handler._get_payload_date(payload, ("dates", "end_date")) == date(2024, 9, 15)


def test_get_payload_date_supports_day_first_policy_dates():
    handler = module.InvoicePocPayload.__new__(module.InvoicePocPayload)

    payload = {
        "invoice_date": "2026-07-29",
        "due_date": "2026-08-12",
        "policy": {
            "start_date": "01/08/2026",
            "end_date": "15/08/2026",
        },
    }

    assert handler._get_payload_date(payload, ("policy", "start_date"), ("invoice_date",)) == date(2026, 8, 1)
    assert handler._get_payload_date(payload, ("policy", "end_date"), ("due_date",)) == date(2026, 8, 15)


def test_get_payload_date_dates_fallback_respects_start_vs_end_context():
    handler = module.InvoicePocPayload.__new__(module.InvoicePocPayload)

    payload = {
        "dates": {
            "start_date": "2026-08-01",
            "end_date": "2026-08-15",
        }
    }

    assert handler._get_payload_date(payload, ("policy", "start_date")) == date(2026, 8, 1)
    assert handler._get_payload_date(payload, ("policy", "end_date")) == date(2026, 8, 15)


def test_get_payload_date_start_context_does_not_pick_invoice_date():
    handler = module.InvoicePocPayload.__new__(module.InvoicePocPayload)

    payload = {
        "invoice_date": "2026-07-29",
        "due_date": "2026-08-12",
        "policy": {
            "start_date": "invalid-date",
        },
    }

    assert handler._get_payload_date(payload, ("policy", "start_date")) is False
