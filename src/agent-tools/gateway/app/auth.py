from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Header, HTTPException
import jwt
from jwt import PyJWKClient


@dataclass(frozen=True)
class WorkloadCaller:
    object_id: str
    app_id: str | None
    tenant_id: str | None
    roles: tuple[str, ...]


@dataclass(frozen=True)
class WorkloadAuthConfig:
    enabled: bool
    tenant_id: str | None
    allowed_issuers: tuple[str, ...]
    audiences: tuple[str, ...]
    allowed_object_ids: tuple[str, ...]
    required_role: str | None


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
    enabled = _env_bool("FARSIGHT_AGENT_TOOLS_ENFORCE_WORKLOAD_AUTH", False)
    tenant_id = os.getenv("FARSIGHT_ENTRA_TENANT_ID", "").strip() or None
    configured_issuers = _csv_env("FARSIGHT_AGENT_TOOLS_ALLOWED_ISSUERS")
    legacy_issuers = _csv_env("FARSIGHT_ENTRA_ALLOWED_ISSUERS")
    issuer = os.getenv("FARSIGHT_AGENT_TOOLS_ISSUER", "").strip()
    derived_issuers: list[str] = []
    if tenant_id:
        derived_issuers.append(f"https://login.microsoftonline.com/{tenant_id}/v2.0")
        derived_issuers.append(f"https://sts.windows.net/{tenant_id}/")
    if issuer:
        derived_issuers.insert(0, issuer)
    allowed_issuers = tuple(dict.fromkeys(configured_issuers or legacy_issuers or tuple(derived_issuers)))
    audiences = _csv_env("FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES")
    allowed_object_ids = _csv_env("FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS")
    required_role = os.getenv("FARSIGHT_AGENT_TOOLS_REQUIRED_APP_ROLE", "").strip() or None
    return WorkloadAuthConfig(
        enabled=enabled,
        tenant_id=tenant_id,
        allowed_issuers=allowed_issuers,
        audiences=audiences,
        allowed_object_ids=allowed_object_ids,
        required_role=required_role,
    )


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    jwks_uri = os.getenv("FARSIGHT_AGENT_TOOLS_JWKS_URI", "").strip() or os.getenv("FARSIGHT_ENTRA_JWKS_URI", "").strip()
    if not jwks_uri:
        tenant_id = os.getenv("FARSIGHT_ENTRA_TENANT_ID", "").strip()
        if not tenant_id:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Gateway workload auth is enabled but FARSIGHT_AGENT_TOOLS_JWKS_URI is empty and "
                    "FARSIGHT_ENTRA_TENANT_ID is not configured."
                ),
            )
        jwks_uri = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    return PyJWKClient(jwks_uri)


def _decode_workload_token(token: str, config: WorkloadAuthConfig) -> dict:
    if not config.allowed_issuers:
        raise HTTPException(
            status_code=500,
            detail=(
                "Gateway workload auth is enabled but no allowed issuer is configured. Set FARSIGHT_ENTRA_TENANT_ID, "
                "FARSIGHT_AGENT_TOOLS_ISSUER, FARSIGHT_AGENT_TOOLS_ALLOWED_ISSUERS, or FARSIGHT_ENTRA_ALLOWED_ISSUERS."
            ),
        )
    if not config.audiences:
        raise HTTPException(
            status_code=500,
            detail="Gateway workload auth is enabled but FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES is empty.",
        )
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=list(config.audiences),
            options={"require": ["iss", "aud", "exp", "tid"]},
        )
        issuer = str(claims.get("iss", "")).strip()
        if issuer not in config.allowed_issuers:
            raise HTTPException(status_code=401, detail="Gateway workload token issuer is not allowed.")
        return claims
    except HTTPException:
        raise
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or unverifiable gateway workload token.") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or unverifiable gateway workload token.") from exc


def _extract_token_roles(claims: dict) -> tuple[str, ...]:
    raw_roles = claims.get("roles") or []
    if isinstance(raw_roles, str):
        return (raw_roles,)
    if isinstance(raw_roles, list):
        return tuple(str(item) for item in raw_roles if item)
    return ()


def _enforce_workload_token_claims(claims: dict, config: WorkloadAuthConfig) -> tuple[str, ...]:
    if config.tenant_id and str(claims.get("tid", "")).strip() != config.tenant_id:
        raise HTTPException(status_code=403, detail="Gateway workload token tenant is not authorized.")

    scopes = str(claims.get("scp", "")).strip()
    if scopes:
        raise HTTPException(status_code=403, detail="Delegated user tokens are not allowed for gateway endpoints.")

    token_type = str(claims.get("idtyp", "")).strip().lower()
    if token_type and token_type != "app":
        raise HTTPException(status_code=403, detail="Only application workload tokens are allowed for gateway endpoints.")

    roles = _extract_token_roles(claims)
    if config.required_role and config.required_role not in roles:
        raise HTTPException(status_code=403, detail="Caller token is missing the required Agent Tools app role.")
    return roles


def require_workload_caller(authorization: str | None = Header(default=None, alias="Authorization")) -> WorkloadCaller:
    config = _workload_auth_config()
    if not config.enabled:
        return WorkloadCaller(object_id="gateway-workload-auth-disabled", app_id=None, tenant_id=None, roles=())

    if not config.allowed_object_ids and not config.required_role:
        raise HTTPException(
            status_code=500,
            detail=(
                "Gateway workload auth is enabled but neither FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS "
                "nor FARSIGHT_AGENT_TOOLS_REQUIRED_APP_ROLE is configured."
            ),
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Bearer token is required.")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Authorization header must be Bearer <token>.")

    claims = _decode_workload_token(token.strip(), config)
    object_id = str(claims.get("oid", "")).strip()
    if not object_id:
        raise HTTPException(status_code=401, detail="Gateway workload token is missing service principal object id (oid).")
    app_id = str(claims.get("appid") or claims.get("azp") or "").strip()
    if not app_id:
        raise HTTPException(status_code=401, detail="Gateway workload token is missing application id (appid/azp).")

    roles = _enforce_workload_token_claims(claims, config)

    if config.allowed_object_ids and object_id not in config.allowed_object_ids:
        raise HTTPException(status_code=403, detail="Caller service principal is not authorized for Agent Tools gateway calls.")

    return WorkloadCaller(object_id=object_id, app_id=app_id, tenant_id=claims.get("tid"), roles=roles)
