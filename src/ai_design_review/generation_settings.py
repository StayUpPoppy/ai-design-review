"""Drawing presentation settings; independent of spring calculation and login identity."""
from __future__ import annotations

from typing import Any


def normalize_generation_settings(
    settings: Any, *, default_username: str = "", allow_blank: bool = False
) -> dict[str, str]:
    if not isinstance(settings, dict):
        raise ValueError("生图设置必须是对象。")
    drawing_model = settings.get("drawing_model", "X型")
    if drawing_model not in ("X型", "Y型"):
        raise ValueError("图纸版式只能选择横版或竖版。")
    username = settings.get("username", default_username)
    if not isinstance(username, str):
        raise ValueError("生图人姓名必须是文本。")
    username = username.strip()
    if not username and not allow_blank:
        raise ValueError("请填写生图人姓名。")
    if len(username) > 256:
        raise ValueError("生图人姓名不能超过256个字符。")
    return {"drawing_model": drawing_model, "username": username}


def resolve_generation_settings(review: dict[str, Any], identity: dict[str, Any] | None = None) -> dict[str, str] | None:
    # Pure/legacy package builders have no login context. Never invent settings
    # when rebuilding an old frozen package or comparing engineering parameters.
    if "generation_settings" not in review and identity is None:
        return None
    identity = identity or {}
    return normalize_generation_settings(
        review.get("generation_settings", {}),
        default_username=str(identity.get("real_name") or identity.get("username") or "").strip(),
    )
