from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from functools import lru_cache
from dataclasses import dataclass
from hashlib import sha256
from time import time
from urllib.parse import unquote

import base64

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.x509.oid import ExtendedKeyUsageOID
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
class DeviceCaller:
    thumbprint: str        # SHA-256 hex, uppercase, no spaces
    subject_cn: str | None
    not_valid_after: datetime


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


def _parse_forwarded_client_cert(header_value: str) -> x509.Certificate:
    """Parse the X-Forwarded-Client-Cert header sent by Azure Container Apps.

    ACA URL-encodes the PEM certificate before placing it in the header.
    """
    pem = unquote(header_value).strip()
    if not pem.startswith("-----BEGIN CERTIFICATE-----"):
        # Some ACA revisions send the raw base64 DER blob without PEM armour.
        try:
            der = __import__("base64").b64decode(pem)
            return x509.load_der_x509_certificate(der)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Device certificate in X-Forwarded-Client-Cert is not parseable.") from exc
    try:
        return x509.load_pem_x509_certificate(pem.encode())
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Device certificate in X-Forwarded-Client-Cert is not parseable.") from exc


def _cert_thumbprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex().upper()


def _cert_subject_cn(cert: x509.Certificate) -> str | None:
    attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    return attrs[0].value if attrs else None


def _cert_has_client_auth_eku(cert: x509.Certificate) -> bool:
    try:
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        return ExtendedKeyUsageOID.CLIENT_AUTH in eku.value
    except x509.ExtensionNotFound:
        return False


@lru_cache(maxsize=1)
def _trusted_device_ca() -> x509.Certificate | None:
    """Load the trusted root/issuing CA certificate from FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM.

    The env var must contain the base64-encoded PEM certificate (i.e. the PEM file
    with header/footer, then base64-encoded again so it is safe as a single-line env var).
    When unset, chain validation is skipped (basic validity + EKU checks still apply).
    """
    raw = os.getenv("FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM", "").strip()
    if not raw:
        return None
    try:
        pem = base64.b64decode(raw)
        return x509.load_pem_x509_certificate(pem)
    except Exception:
        return None


def _verify_cert_issued_by(cert: x509.Certificate, ca: x509.Certificate) -> bool:
    """Check that cert was signed by ca using the CA public key."""
    if cert.issuer != ca.subject:
        return False
    pub = ca.public_key()
    try:
        if isinstance(pub, RSAPublicKey):
            pub.verify(cert.signature, cert.tbs_certificate_bytes, asym_padding.PKCS1v15(), cert.signature_hash_algorithm)  # type: ignore[arg-type]
        elif isinstance(pub, EllipticCurvePublicKey):
            pub.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))  # type: ignore[arg-type]
        else:
            return False
        return True
    except Exception:
        return False


def require_device_cert(
    x_forwarded_client_cert: str | None = Header(default=None, alias="X-Forwarded-Client-Cert"),
) -> DeviceCaller:
    """Validate the device client certificate forwarded by the Container Apps ingress.

    Requires FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH=true to enforce; passthrough when disabled
    (allows local dev without a certificate).
    """
    enforce = _env_bool("FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH", False)

    if not enforce:
        return DeviceCaller(
            thumbprint="device-cert-auth-disabled",
            subject_cn=None,
            not_valid_after=datetime.max.replace(tzinfo=timezone.utc),
        )

    if not x_forwarded_client_cert:
        raise HTTPException(status_code=401, detail="Device client certificate is required (X-Forwarded-Client-Cert missing).")

    cert = _parse_forwarded_client_cert(x_forwarded_client_cert)

    now = datetime.now(timezone.utc)
    not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
    if now > not_after:
        raise HTTPException(status_code=401, detail="Device client certificate has expired.")

    not_before = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=timezone.utc)
    if now < not_before:
        raise HTTPException(status_code=401, detail="Device client certificate is not yet valid.")

    if not _cert_has_client_auth_eku(cert):
        raise HTTPException(status_code=401, detail="Device client certificate does not carry the Client Authentication EKU.")

    ca = _trusted_device_ca()
    if ca is not None and not _verify_cert_issued_by(cert, ca):
        raise HTTPException(status_code=401, detail="Device client certificate was not issued by the configured trusted CA.")

    return DeviceCaller(
        thumbprint=_cert_thumbprint(cert),
        subject_cn=_cert_subject_cn(cert),
        not_valid_after=not_after,
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
