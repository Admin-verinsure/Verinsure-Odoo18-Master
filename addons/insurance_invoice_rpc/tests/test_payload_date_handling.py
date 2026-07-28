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
