from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from hashlib import sha256
from time import time

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class AdminActor:
    actor_id: str
    actor_name: str | None
    groups: tuple[str, ...]


def _internal_auth_secret() -> str:
    return os.getenv("FARSIGHT_API_INTERNAL_AUTH_SECRET", "").strip()


def sign_admin_context(actor_id: str, actor_name: str, groups: str, expires: str, secret: str) -> str:
    payload = "\n".join([actor_id, actor_name, groups, expires])
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()


def require_admin_actor(
    x_farsight_admin_actor: str | None = Header(default=None, alias="X-FarSight-Admin-Actor"),
    x_farsight_admin_name: str | None = Header(default=None, alias="X-FarSight-Admin-Name"),
    x_farsight_admin_groups: str | None = Header(default="", alias="X-FarSight-Admin-Groups"),
    x_farsight_admin_expires: str | None = Header(default=None, alias="X-FarSight-Admin-Expires"),
    x_farsight_admin_signature: str | None = Header(default=None, alias="X-FarSight-Admin-Signature"),
) -> AdminActor:
    secret = _internal_auth_secret()
    if not secret:
        raise HTTPException(status_code=403, detail="API internal authorization secret is not configured.")
    if not x_farsight_admin_actor or not x_farsight_admin_expires or not x_farsight_admin_signature:
        raise HTTPException(status_code=403, detail="Signed FarSight admin context is required.")
    try:
        expires = int(x_farsight_admin_expires)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid FarSight admin context expiry.") from exc
    if expires < int(time()):
        raise HTTPException(status_code=403, detail="FarSight admin context has expired.")

    groups = x_farsight_admin_groups or ""
    actor_name = x_farsight_admin_name or ""
    expected = sign_admin_context(x_farsight_admin_actor, actor_name, groups, x_farsight_admin_expires, secret)
    if not hmac.compare_digest(expected, x_farsight_admin_signature):
        raise HTTPException(status_code=403, detail="Invalid FarSight admin context signature.")

    return AdminActor(
        actor_id=x_farsight_admin_actor,
        actor_name=actor_name or None,
        groups=tuple(item for item in groups.split(",") if item),
    )
