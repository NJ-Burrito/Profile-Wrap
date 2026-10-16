from __future__ import annotations

import json
from pathlib import Path

import pytest

from profile_wrap import schemalite as sl

REPO = Path(__file__).resolve().parents[3]


def errs(inst, schema):
    return sl.validate(inst, schema)


def test_types_and_bool_is_not_integer():
    assert errs(3, {"type": "integer"}) == []
    assert errs(True, {"type": "integer"})
    assert errs(2.5, {"type": "number"}) == []
    assert errs("x", {"type": ["string", "null"]}) == []
    assert errs(None, {"type": ["string", "null"]}) == []
    assert "expected string" in errs(1, {"type": "string"})[0]


def test_enum_const_and_strings():
    assert errs("a", {"enum": ["a", "b"]}) == []
    assert "is not one of" in errs("c", {"enum": ["a", "b"]})[0]
    assert errs(1, {"const": 2})
    s = {"type": "string", "minLength": 2, "maxLength": 3, "pattern": "^[a-z]+$"}
    assert errs("ab", s) == []
    assert errs("a", s) and errs("abcd", s) and errs("A1", s)


def test_numbers():
    s = {"type": "number", "minimum": 1, "maximum": 3, "exclusiveMinimum": 0, "exclusiveMaximum": 4}
    assert errs(2, s) == []
    assert errs(0, s) and errs(4, s)
    assert errs(0.5, {"type": "number", "exclusiveMinimum": 0}) == []
    assert errs(0, {"type": "number", "exclusiveMinimum": 0})
    assert errs(5, {"type": "number", "exclusiveMaximum": 5})


def test_arrays():
    s = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2,
         "uniqueItems": True}
    assert errs([1, 2], s) == []
    assert errs([], s) and errs([1, 2, 3], s) and errs([1, 1], s) and errs([1, "x"], s)


def test_objects_required_additional_pattern():
    s = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"],
         "additionalProperties": False}
    assert errs({"a": 1}, s) == []
    assert "missing required key 'a'" in errs({}, s)[0]
    assert "b: unknown key" in " ".join(errs({"a": 1, "b": 2}, s))
    s2 = {"type": "object", "additionalProperties": {"type": "integer"}}
    assert errs({"x": 1}, s2) == [] and errs({"x": "no"}, s2)
    s3 = {"type": "object", "patternProperties": {"^n_": {"type": "integer"}},
          "additionalProperties": False}
    assert errs({"n_a": 1}, s3) == []
    assert errs({"n_a": "x"}, s3) and errs({"z": 1}, s3)


def test_combinators_and_conditionals():
    assert errs(1, {"anyOf": [{"type": "string"}, {"type": "integer"}]}) == []
    assert errs([], {"anyOf": [{"type": "string"}, {"type": "integer"}]})
    assert errs(1, {"oneOf": [{"type": "integer"}, {"type": "number"}]})  # matches both
    assert errs("x", {"oneOf": [{"type": "integer"}, {"type": "string"}]}) == []
    assert errs(1, {"allOf": [{"type": "integer"}, {"minimum": 2}]})
    assert errs(1, {"not": {"type": "integer"}})
    cond = {"if": {"properties": {"k": {"const": "a"}}, "required": ["k"]},
            "then": {"required": ["v"]}, "else": {"required": ["w"]}}
    assert errs({"k": "a", "v": 1}, cond) == []
    assert errs({"k": "a"}, cond)
    assert errs({"k": "b", "w": 1}, cond) == []
    assert errs({"k": "b"}, cond)


def test_ref_and_unsupported():
    schema = {"definitions": {"n": {"type": "integer"}}, "type": "object",
              "properties": {"x": {"$ref": "#/definitions/n"}}}
    assert errs({"x": 1}, schema) == []
    assert errs({"x": "no"}, schema)
    with pytest.raises(sl.SchemaError):
        errs(1, {"$ref": "#/definitions/missing"})
    with pytest.raises(sl.SchemaError):
        errs(1, {"$ref": "http://example.invalid/x"})
    with pytest.raises(sl.SchemaError):
        errs(1, {"dependencies": {}})
    assert errs(1, {"x-note": "ignored", "type": "integer"}) == []
    assert errs("x", True) == [] and errs("x", False)
    with pytest.raises(sl.SchemaError):
        errs(1, 5)


def test_formats():
    assert errs("2026-10-16", {"format": "date"}) == []
    assert errs("2026-13-40", {"format": "date"})
    assert errs("2026-10-16T09:00:00+03:00", {"format": "date-time"}) == []
    assert "UTC offset" in errs("2026-10-16T09:00:00", {"format": "date-time"})[0]
    assert errs("nope", {"format": "date-time"})
    assert errs("09:30", {"format": "hhmm"}) == []
    assert errs("9:30", {"format": "hhmm"}) and errs("24:00", {"format": "hhmm"})


def test_validate_file(tmp_path):
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps({"type": "object", "required": ["a"]}), encoding="utf-8")
    ok = tmp_path / "ok.json"
    ok.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
    assert sl.validate_file(ok, schema) == []
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert "invalid JSON" in sl.validate_file(bad, schema)[0]


def _walk(node, where, bad):
    if not isinstance(node, dict):
        return
    for key in node:
        if key not in sl._KNOWN and not key.startswith("x-"):
            bad.append(f"{where}: {key}")
    for key in ("properties", "patternProperties", "definitions", "$defs"):
        for name, sub in node.get(key, {}).items():
            _walk(sub, f"{where}.{name}", bad)
    for key in ("items", "additionalProperties", "not", "if", "then", "else"):
        if isinstance(node.get(key), dict):
            _walk(node[key], f"{where}.{key}", bad)
    for key in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(node.get(key, [])):
            _walk(sub, f"{where}.{key}[{i}]", bad)


@pytest.mark.parametrize("name", sorted(p.name for p in (REPO / "schema").glob("*.schema.json")))
def test_every_shipped_schema_uses_only_supported_keywords(name):
    bad = []
    _walk(sl.load_schema(REPO / "schema" / name), name, bad)
    assert bad == []
