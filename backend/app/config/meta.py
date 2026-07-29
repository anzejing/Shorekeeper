"""Config metadata — maps Pydantic fields to ConfigItem for the frontend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

# Group metadata: display name and sort order
GROUP_META: dict[str, tuple[str, int]] = {
    "server": ("服务器", 1),
    "runtime": ("Runtime", 2),
    "log": ("日志", 3),
    "storage": ("存储", 4),
    "security": ("安全", 5),
    "ui": ("界面", 6),
}


@dataclass
class ConfigItem:
    """One config entry exposed to the frontend."""

    key: str
    label: str
    description: str
    type: str
    value: Any
    default: Any
    required: bool = False
    secret: bool = False
    group: str = ""
    order: int = 0
    options: list[Any] = field(default_factory=list)


# Python type → frontend type mapping
_TYPE_MAP: dict[str, str] = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
}


def _resolve_type(field_info: Any) -> str:
    """Resolve Pydantic field type to frontend config type."""
    ann = field_info.annotation
    if ann is None:
        return "string"

    type_name = getattr(ann, "__name__", str(ann))

    # Check for options (select type)
    extras = getattr(field_info, "json_schema_extra", None) or {}
    if "options" in extras:
        return "select"

    return _TYPE_MAP.get(type_name, "string")


def build_config_items(config: BaseModel) -> list[dict[str, Any]]:
    """Convert an AppConfig instance into a list of ConfigItem dicts grouped for the frontend."""
    groups: dict[str, dict[str, Any]] = {}

    for idx, (group_name, fi) in enumerate(type(config).model_fields.items()):
        group_value = getattr(config, group_name)
        if not isinstance(group_value, BaseModel):
            continue

        label, order = GROUP_META.get(group_name, (group_name, idx + 1))
        items: list[dict[str, Any]] = []

        for field_name, fi in type(group_value).model_fields.items():
            extras = getattr(fi, "json_schema_extra", None) or {}
            secret = bool(extras.get("secret", False))
            options = extras.get("options", [])

            value = getattr(group_value, field_name)
            default = fi.default if fi.default is not None else fi.default_factory() if fi.default_factory else None

            # Mask secret values
            display_value = "***" if secret and value else value

            item = ConfigItem(
                key=f"{group_name}.{field_name}",
                label=fi.description or field_name,
                description=fi.description or "",
                type=_resolve_type(fi),
                value=display_value,
                default=default,
                required=fi.is_required(),
                secret=secret,
                group=label,
                order=items.__len__(),
                options=options if isinstance(options, list) else [],
            )
            items.append(item.__dict__)

        groups[group_name] = {"group": label, "order": order, "items": items}

    # Sort by order
    result = sorted(groups.values(), key=lambda g: g["order"])
    return result
