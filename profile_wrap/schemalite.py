"""A small JSON Schema subset validator (stdlib only).

Supported keywords: type, enum, const, properties, required,
additionalProperties (bool or schema), patternProperties, items (schema),
minItems, maxItems, uniqueItems, minLength, maxLength, pattern, minimum,
maximum, exclusiveMinimum, exclusiveMaximum, oneOf, anyOf, allOf, not,
if/then/else, $ref (local ``#/...`` pointers), format (date, date-time, hhmm)
and the annotations title/description/default/$schema/$id/$comment/x-*, which
are ignored.

Errors are plain strings of the form ``<json path>: <message>``.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}

_KNOWN = {
    "type", "enum", "const", "properties", "required", "additionalProperties",
    "patternProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength",
    "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "oneOf", "anyOf", "allOf", "not", "if", "then", "else", "$ref", "format",
    "title", "description", "default", "$schema", "$id", "$comment", "definitions",
    "$defs", "examples",
}


class SchemaError(Exception):
    """The schema itself is unusable (bad $ref, unknown keyword)."""


def load_schema(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _type_name(value: Any) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _TYPES[name](value):
            return name
    return type(value).__name__


def _resolve(ref: str, root: Dict[str, Any]) -> Any:
    if not ref.startswith("#"):
        raise SchemaError(f"only local $ref is supported: {ref}")
    node: Any = root
    for part in [p for p in ref[1:].split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"unresolvable $ref: {ref}")
        node = node[part]
    return node


def _check_format(fmt: str, value: str) -> Optional[str]:
    if fmt == "date":
        try:
            _dt.date.fromisoformat(value)
        except ValueError:
            return "is not a date (YYYY-MM-DD)"
    elif fmt == "date-time":
        try:
            parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "is not an ISO 8601 date-time"
        if parsed.tzinfo is None:
            return "needs a UTC offset (for example +03:00)"
    elif fmt == "hhmm":
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            return "is not HH:MM"
    return None


def _validate(inst: Any, schema: Any, root: Dict[str, Any], path: str, errors: List[str]) -> None:
    if schema is True or schema == {}:
        return
    if schema is False:
        errors.append(f"{path}: not allowed here")
        return
    if not isinstance(schema, dict):
        raise SchemaError(f"{path}: schema must be an object or boolean")
    for key in schema:
        if key not in _KNOWN and not key.startswith("x-"):
            raise SchemaError(f"unsupported schema keyword: {key}")
    if "$ref" in schema:
        _validate(inst, _resolve(schema["$ref"], root), root, path, errors)
        if len(schema) == 1:
            return

    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_TYPES[n](inst) for n in names):
            errors.append(f"{path}: expected {' or '.join(names)}, got {_type_name(inst)}")
            return

    if "const" in schema and inst != schema["const"]:
        errors.append(f"{path}: must equal {json.dumps(schema['const'], ensure_ascii=False)}")
    if "enum" in schema and inst not in schema["enum"]:
        opts = ", ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
        errors.append(f"{path}: {json.dumps(inst, ensure_ascii=False)} is not one of {opts}")

    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errors.append(f"{path}: does not match pattern {schema['pattern']}")
        if "format" in schema:
            problem = _check_format(schema["format"], inst)
            if problem:
                errors.append(f"{path}: {problem}")

    if _TYPES["number"](inst):
        if "minimum" in schema and inst < schema["minimum"]:
            errors.append(f"{path}: {inst} is below the minimum {schema['minimum']}")
        if "maximum" in schema and inst > schema["maximum"]:
            errors.append(f"{path}: {inst} is above the maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and inst <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: must be above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and inst >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: must be below {schema['exclusiveMaximum']}")

    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen: List[str] = []
            for item in inst:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    errors.append(f"{path}: items must be unique ({key[:40]} repeats)")
                    break
                seen.append(key)
        if "items" in schema:
            for i, item in enumerate(inst):
                _validate(item, schema["items"], root, f"{path}[{i}]", errors)

    if isinstance(inst, dict):
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for name in schema.get("required", []):
            if name not in inst:
                errors.append(f"{path}: missing required key '{name}'")
        for name, value in inst.items():
            sub = f"{path}.{name}" if path else name
            if name in props:
                _validate(value, props[name], root, sub, errors)
                continue
            matched = False
            for pat, pschema in patterns.items():
                if re.search(pat, name):
                    matched = True
                    _validate(value, pschema, root, sub, errors)
            if matched:
                continue
            extra = schema.get("additionalProperties", True)
            if extra is False:
                errors.append(f"{sub}: unknown key")
            elif isinstance(extra, dict):
                _validate(value, extra, root, sub, errors)

    for kw in ("allOf",):
        for sub_schema in schema.get(kw, []):
            _validate(inst, sub_schema, root, path, errors)
    if "anyOf" in schema:
        if not any(not _errs(inst, s, root, path) for s in schema["anyOf"]):
            errors.append(f"{path}: matches none of the allowed shapes")
    if "oneOf" in schema:
        hits = sum(1 for s in schema["oneOf"] if not _errs(inst, s, root, path))
        if hits != 1:
            errors.append(f"{path}: must match exactly one allowed shape (matched {hits})")
    if "not" in schema and not _errs(inst, schema["not"], root, path):
        errors.append(f"{path}: matches a forbidden shape")
    if "if" in schema:
        branch = "then" if not _errs(inst, schema["if"], root, path) else "else"
        if branch in schema:
            _validate(inst, schema[branch], root, path, errors)


def _errs(inst: Any, schema: Any, root: Dict[str, Any], path: str) -> List[str]:
    out: List[str] = []
    _validate(inst, schema, root, path, out)
    return out


def validate(instance: Any, schema: Dict[str, Any]) -> List[str]:
    """Return a list of error strings; an empty list means valid."""
    errors: List[str] = []
    _validate(instance, schema, schema, "$", errors)
    return errors


def validate_file(instance_path: Path, schema_path: Path) -> List[str]:
    text = Path(instance_path).read_text(encoding="utf-8-sig")
    try:
        inst = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"$: invalid JSON ({exc.msg} at line {exc.lineno})"]
    return validate(inst, load_schema(schema_path))
