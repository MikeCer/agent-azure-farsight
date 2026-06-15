from __future__ import annotations

import hmac
import os
from functools import lru_cache
from dataclasses import dataclass
from hashlib import sha256
from time import time

from fastapi import Header, HTTPException
import jwt
from jwt import PyJWKClient


@dataclass(frozen=True)
class AdminActor:
    actor_id: str
    actor_name: str | None
    groups: tuple[str, ...]


@dataclass(frozen=True)
class WorkloadCaller:
    object_id: str
    app_id: str | None
    tenant_id: str | None
    roles: tuple[str, ...]


@dataclass(frozen=True)
class WorkloadAuthConfig:
    enabled: bool
    issuer: str
    audiences: tuple[str, ...]
    allowed_object_ids: tuple[str, ...]
    required_role: str | None


def _internal_auth_secret() -> str:
    return os.getenv("FARSIGHT_API_INTERNAL_AUTH_SECRET", "").strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@lru_cache(maxsize=1)
def _workload_auth_config() -> WorkloadAuthConfig:
    enabled = _env_bool("FARSIGHT_API_ENFORCE_WORKLOAD_AUTH", False)
    tenant_id = os.getenv("FARSIGHT_ENTRA_TENANT_ID", "").strip()
    issuer = os.getenv("FARSIGHT_ENTRA_ISSUER", "").strip()
    if not issuer and tenant_id:
        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audiences = _csv_env("FARSIGHT_API_ALLOWED_AUDIENCES")
    allowed_object_ids = _csv_env("FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS")
    required_role = os.getenv("FARSIGHT_API_REQUIRED_APP_ROLE", "").strip() or None
    return WorkloadAuthConfig(
        enabled=enabled,
        issuer=issuer,
        audiences=audiences,
        allowed_object_ids=allowed_object_ids,
        required_role=required_role,
    )


@lru_cache(maxsize=1)
def _jwk_client(issuer: str) -> PyJWKClient:
    jwks_uri = os.getenv("FARSIGHT_ENTRA_JWKS_URI", "").strip() or f"{issuer.rstrip('/')}/discovery/v2.0/keys"
    return PyJWKClient(jwks_uri)


def _decode_workload_token(token: str, config: WorkloadAuthConfig) -> dict:
    if not config.issuer:
        raise HTTPException(
            status_code=500,
            detail="Workload auth is enabled but FARSIGHT_ENTRA_TENANT_ID or FARSIGHT_ENTRA_ISSUER is not configured.",
        )
    if not config.audiences:
        raise HTTPException(
            status_code=500,
            detail="Workload auth is enabled but FARSIGHT_API_ALLOWED_AUDIENCES is empty.",
        )
    try:
        signing_key = _jwk_client(config.issuer).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=list(config.audiences),
            issuer=config.issuer,
            options={"require": ["iss", "aud", "exp"]},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or unverifiable workload token.") from exc


def require_workload_caller(authorization: str | None = Header(default=None, alias="Authorization")) -> WorkloadCaller:
    config = _workload_auth_config()
    if not config.enabled:
        return WorkloadCaller(object_id="workload-auth-disabled", app_id=None, tenant_id=None, roles=())
    if not config.allowed_object_ids and not config.required_role:
        raise HTTPException(
            status_code=500,
            detail=(
                "Workload auth is enabled but neither FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS "
                "nor FARSIGHT_API_REQUIRED_APP_ROLE is configured."
            ),
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Bearer token is required.")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Authorization header must be Bearer <token>.")

    claims = _decode_workload_token(token.strip(), config)
    object_id = (claims.get("oid") or "").strip()
    if not object_id:
        raise HTTPException(status_code=401, detail="Workload token is missing service principal object id (oid).")
    if config.allowed_object_ids and object_id not in config.allowed_object_ids:
        raise HTTPException(status_code=403, detail="Caller service principal is not authorized for FarSight API workload calls.")

    raw_roles = claims.get("roles") or []
    if isinstance(raw_roles, str):
        roles = (raw_roles,)
    elif isinstance(raw_roles, list):
        roles = tuple(str(item) for item in raw_roles if item)
    else:
        roles = ()
    if config.required_role and config.required_role not in roles:
        raise HTTPException(status_code=403, detail="Caller token is missing the required FarSight API app role.")

    return WorkloadCaller(
        object_id=object_id,
        app_id=(claims.get("appid") or claims.get("azp")),
        tenant_id=claims.get("tid"),
        roles=roles,
    )


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
