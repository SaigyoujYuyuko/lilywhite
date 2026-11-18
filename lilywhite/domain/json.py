"""精确JSON类型与运行时解码边界。"""

import json
from typing import cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]
type JsonFlatObject = dict[str, JsonScalar]


def parse_json_object(data: str | bytes) -> JsonObject:
    """解码并递归校验JSON对象。"""
    value: object = json.loads(data)
    return as_json_object(value)


def as_json_object(value: object) -> JsonObject:
    """要求对象键为字符串且值可表示为JSON。"""
    if not isinstance(value, dict):
        raise ValueError("Body is not a JSON object.")
    source = cast(dict[object, object], value)
    result: JsonObject = {}
    for key, item in source.items():
        if not isinstance(key, str):
            raise ValueError("JSON object keys must be strings.")
        result[key] = as_json_value(item)
    return result


def as_json_value(value: object) -> JsonValue:
    """递归收窄未知JSON值。"""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        items = cast(list[object], value)
        return [as_json_value(item) for item in items]
    if isinstance(value, dict):
        return as_json_object(value)
    raise ValueError(f"Unsupported JSON value type: {type(value).__name__}")


__all__ = [
    "JsonArray",
    "JsonFlatObject",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "as_json_object",
    "as_json_value",
    "parse_json_object",
]
