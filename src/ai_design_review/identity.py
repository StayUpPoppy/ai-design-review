from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote

from starlette.requests import Request


class IdentityError(RuntimeError):
    """Raised when the request cannot be associated with a trusted user context."""


@dataclass(frozen=True)
class IdentityContext:
    user_id: str
    username: str
    real_name: str
    org_id: str
    org_name: str
    source: str

    @property
    def is_mock(self) -> bool:
        return self.source == "mock"

    def as_public_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "is_mock": self.is_mock,
            "identity_display_enabled": identity_display_enabled(),
        }

    def as_owner_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "real_name": self.real_name,
            "org_id": self.org_id,
            "org_name": self.org_name,
        }

    def as_audit_actor(self) -> dict[str, str]:
        return {
            "erp_user_id": self.user_id,
            "username": self.username,
            "display_name": self.real_name or self.username,
            "department_id": self.org_id,
            "factory_name": self.org_name,
        }


def identity_mode() -> str:
    value = str(os.getenv("AI_REVIEW_IDENTITY_MODE", "mock") or "mock").strip().lower()
    if value not in {"mock", "cookie_json"}:
        raise IdentityError("Identity mode is not configured correctly.")
    return value


def identity_display_enabled() -> bool:
    value = str(os.getenv("AI_REVIEW_SHOW_IDENTITY", "true") or "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def resolve_request_identity(request: Request) -> IdentityContext:
    mode = identity_mode()
    if mode == "mock":
        return _mock_identity()
    return _cookie_json_identity(request)


def _mock_identity() -> IdentityContext:
    return IdentityContext(
        user_id=_required_text(os.getenv("AI_REVIEW_MOCK_USER_ID", "local-user"), "mock user ID"),
        username=_required_text(os.getenv("AI_REVIEW_MOCK_USERNAME", "local-user"), "mock username"),
        real_name=_optional_text(os.getenv("AI_REVIEW_MOCK_REAL_NAME"))
        or _required_text(os.getenv("AI_REVIEW_MOCK_USERNAME", "local-user"), "mock username"),
        org_id=_required_text(os.getenv("AI_REVIEW_MOCK_ORG_ID", "local-org"), "mock organization ID"),
        org_name=_required_text(os.getenv("AI_REVIEW_MOCK_ORG_NAME", "Local Factory"), "mock organization name"),
        source="mock",
    )


def _cookie_json_identity(request: Request) -> IdentityContext:
    cookie_name = str(os.getenv("ERP_IDENTITY_COOKIE_NAME", "erp_review_identity") or "erp_review_identity").strip()
    raw_cookie = request.cookies.get(cookie_name)
    if not raw_cookie:
        raise IdentityError("ERP identity cookie is missing.")
    try:
        payload = json.loads(unquote(str(raw_cookie)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IdentityError("ERP identity cookie is invalid.") from exc
    if not isinstance(payload, dict):
        raise IdentityError("ERP identity cookie is invalid.")
    return IdentityContext(
        user_id=_required_text(payload.get("userId"), "userId"),
        username=_required_text(payload.get("username"), "username"),
        real_name=_optional_text(payload.get("realName")) or _required_text(payload.get("username"), "username"),
        org_id=_required_text(payload.get("currentOrgId"), "currentOrgId"),
        org_name=_required_text(payload.get("currentOrgName"), "currentOrgName"),
        source="erp_cookie_json",
    )


def _required_text(value: Any, label: str) -> str:
    text = _optional_text(value)
    if not text:
        raise IdentityError(f"ERP identity field '{label}' is missing.")
    return text


def _optional_text(value: Any) -> str:
    return str(value or "").strip()[:256]
