from __future__ import annotations

import hmac
import os
import re
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
class DeviceAuthConfig:
    enforce: bool
    require_trusted_ca: bool
    allowed_thumbprints: tuple[str, ...]
    denied_thumbprints: tuple[str, ...]
    allowed_device_ids: tuple[str, ...]
    denied_device_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkloadAuthConfig:
    enabled: bool
    tenant_id: str | None
    allowed_issuers: tuple[str, ...]
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
    tenant_id = os.getenv("FARSIGHT_ENTRA_TENANT_ID", "").strip() or None
    configured_issuers = _csv_env("FARSIGHT_ENTRA_ALLOWED_ISSUERS")
    issuer = os.getenv("FARSIGHT_ENTRA_ISSUER", "").strip()
    derived_issuers: list[str] = []
    if tenant_id:
        derived_issuers.append(f"https://login.microsoftonline.com/{tenant_id}/v2.0")
        derived_issuers.append(f"https://sts.windows.net/{tenant_id}/")
    if issuer:
        derived_issuers.insert(0, issuer)
    allowed_issuers = tuple(dict.fromkeys(configured_issuers or tuple(derived_issuers)))
    audiences = _csv_env("FARSIGHT_API_ALLOWED_AUDIENCES")
    allowed_object_ids = _csv_env("FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS")
    required_role = os.getenv("FARSIGHT_API_REQUIRED_APP_ROLE", "").strip() or None
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
    jwks_uri = os.getenv("FARSIGHT_ENTRA_JWKS_URI", "").strip()
    if not jwks_uri:
        tenant_id = os.getenv("FARSIGHT_ENTRA_TENANT_ID", "").strip()
        if not tenant_id:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Workload auth is enabled but FARSIGHT_ENTRA_JWKS_URI is empty and "
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
                "Workload auth is enabled but no allowed issuer is configured. Set FARSIGHT_ENTRA_TENANT_ID, "
                "FARSIGHT_ENTRA_ISSUER, or FARSIGHT_ENTRA_ALLOWED_ISSUERS."
            ),
        )
    if not config.audiences:
        raise HTTPException(
            status_code=500,
            detail="Workload auth is enabled but FARSIGHT_API_ALLOWED_AUDIENCES is empty.",
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
            raise HTTPException(status_code=401, detail="Workload token issuer is not allowed.")
        return claims
    except HTTPException:
        raise
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or unverifiable workload token.") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or unverifiable workload token.") from exc


def _extract_token_roles(claims: dict) -> tuple[str, ...]:
    raw_roles = claims.get("roles") or []
    if isinstance(raw_roles, str):
        return (raw_roles,)
    if isinstance(raw_roles, list):
        return tuple(str(item) for item in raw_roles if item)
    return ()


def _enforce_workload_token_claims(claims: dict, config: WorkloadAuthConfig) -> tuple[str, ...]:
    if config.tenant_id and str(claims.get("tid", "")).strip() != config.tenant_id:
        raise HTTPException(status_code=403, detail="Workload token tenant is not authorized.")

    scopes = str(claims.get("scp", "")).strip()
    if scopes:
        raise HTTPException(status_code=403, detail="Delegated user tokens are not allowed for workload endpoints.")

    token_type = str(claims.get("idtyp", "")).strip().lower()
    if token_type and token_type != "app":
        raise HTTPException(status_code=403, detail="Only application workload tokens are allowed.")

    roles = _extract_token_roles(claims)
    if config.required_role and config.required_role not in roles:
        raise HTTPException(status_code=403, detail="Caller token is missing the required FarSight API app role.")

    return roles


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
    app_id = (claims.get("appid") or claims.get("azp") or "").strip()
    if not app_id:
        raise HTTPException(status_code=401, detail="Workload token is missing application id (appid/azp).")

    roles = _enforce_workload_token_claims(claims, config)

    if config.allowed_object_ids and object_id not in config.allowed_object_ids:
        raise HTTPException(status_code=403, detail="Caller service principal is not authorized for FarSight API workload calls.")

    return WorkloadCaller(
        object_id=object_id,
        app_id=app_id,
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
            der = base64.b64decode(pem)
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


def _cert_is_ca(cert: x509.Certificate) -> bool:
    try:
        basic_constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        return bool(basic_constraints.value.ca)
    except x509.ExtensionNotFound:
        return False


def _cert_allows_digital_signature(cert: x509.Certificate) -> bool:
    try:
        key_usage = cert.extensions.get_extension_for_class(x509.KeyUsage)
        return bool(key_usage.value.digital_signature)
    except x509.ExtensionNotFound:
        return True


def _normalize_thumbprint(value: str) -> str:
    return value.replace(" ", "").upper()


def _load_pem_certificates(blob: bytes) -> tuple[x509.Certificate, ...]:
    certs: list[x509.Certificate] = []
    pattern = re.compile(b"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL)
    for match in pattern.findall(blob):
        certs.append(x509.load_pem_x509_certificate(match))
    return tuple(certs)


@lru_cache(maxsize=1)
def _device_auth_config() -> DeviceAuthConfig:
    enforce = _env_bool("FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH", False)
    require_trusted_ca = _env_bool("FARSIGHT_API_REQUIRE_DEVICE_CERT_TRUSTED_CA", True)
    allowed_thumbprints = tuple(_normalize_thumbprint(item) for item in _csv_env("FARSIGHT_API_ALLOWED_DEVICE_CERT_THUMBPRINTS"))
    denied_thumbprints = tuple(_normalize_thumbprint(item) for item in _csv_env("FARSIGHT_API_DENIED_DEVICE_CERT_THUMBPRINTS"))
    allowed_device_ids = _csv_env("FARSIGHT_API_ALLOWED_DEVICE_IDS")
    denied_device_ids = _csv_env("FARSIGHT_API_DENIED_DEVICE_IDS")
    return DeviceAuthConfig(
        enforce=enforce,
        require_trusted_ca=require_trusted_ca,
        allowed_thumbprints=allowed_thumbprints,
        denied_thumbprints=denied_thumbprints,
        allowed_device_ids=allowed_device_ids,
        denied_device_ids=denied_device_ids,
    )


@lru_cache(maxsize=1)
def _trusted_device_cas() -> tuple[x509.Certificate, ...]:
    """Load trusted root/issuing CA certificates from FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM.

    Supports either raw PEM bundle content or base64-encoded PEM bundle content.
    """
    raw = os.getenv("FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM", "").strip()
    if not raw:
        return ()
    try:
        if "-----BEGIN CERTIFICATE-----" in raw:
            return _load_pem_certificates(raw.encode())
        decoded = base64.b64decode(raw)
        certs = _load_pem_certificates(decoded)
        if certs:
            return certs
        return (x509.load_pem_x509_certificate(decoded),)
    except Exception:
        return ()


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


def _verify_cert_chained_to_trusted_cas(cert: x509.Certificate, trusted_cas: tuple[x509.Certificate, ...]) -> bool:
    if not trusted_cas:
        return False
    by_subject: dict[str, list[x509.Certificate]] = {}
    for candidate in trusted_cas:
        by_subject.setdefault(candidate.subject.rfc4514_string(), []).append(candidate)

    visited: set[str] = set()

    def _walk(current: x509.Certificate, depth: int = 0) -> bool:
        if depth > 8:
            return False
        issuer_key = current.issuer.rfc4514_string()
        for issuer in by_subject.get(issuer_key, []):
            issuer_id = _cert_thumbprint(issuer)
            edge = f"{_cert_thumbprint(current)}->{issuer_id}"
            if edge in visited:
                continue
            visited.add(edge)
            if not _verify_cert_issued_by(current, issuer):
                continue
            if issuer.issuer == issuer.subject and _verify_cert_issued_by(issuer, issuer):
                return True
            if _walk(issuer, depth + 1):
                return True
        return False

    return _walk(cert)


def require_bound_device_id(device: DeviceCaller, claimed_device_id: str) -> None:
    if device.thumbprint == "device-cert-auth-disabled":
        return
    cert_device_id = (device.subject_cn or "").strip()
    if not cert_device_id:
        raise HTTPException(status_code=401, detail="Device client certificate must contain a subject CN for device identity binding.")
    if cert_device_id != claimed_device_id:
        raise HTTPException(status_code=403, detail="Device certificate subject does not match the claimed device_id.")


def require_device_cert(
    x_forwarded_client_cert: str | None = Header(default=None, alias="X-Forwarded-Client-Cert"),
) -> DeviceCaller:
    """Validate the device client certificate forwarded by the Container Apps ingress.

    Requires FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH=true to enforce; passthrough when disabled
    (allows local dev without a certificate).
    """
    config = _device_auth_config()
    if not config.enforce:
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

    if _cert_is_ca(cert):
        raise HTTPException(status_code=401, detail="Device client certificate cannot be a CA certificate.")
    if not _cert_allows_digital_signature(cert):
        raise HTTPException(status_code=401, detail="Device client certificate key usage does not allow digital signature.")

    thumbprint = _cert_thumbprint(cert)
    if config.denied_thumbprints and thumbprint in config.denied_thumbprints:
        raise HTTPException(status_code=403, detail="Device certificate thumbprint is denied.")
    if config.allowed_thumbprints and thumbprint not in config.allowed_thumbprints:
        raise HTTPException(status_code=403, detail="Device certificate thumbprint is not in the allowed list.")

    subject_cn = (_cert_subject_cn(cert) or "").strip()
    if not subject_cn:
        raise HTTPException(status_code=401, detail="Device client certificate must contain a subject CN.")
    if config.denied_device_ids and subject_cn in config.denied_device_ids:
        raise HTTPException(status_code=403, detail="Device identity is denied.")
    if config.allowed_device_ids and subject_cn not in config.allowed_device_ids:
        raise HTTPException(status_code=403, detail="Device identity is not in the allowed list.")

    trusted_cas = _trusted_device_cas()
    if config.require_trusted_ca and not trusted_cas:
        raise HTTPException(
            status_code=500,
            detail="Device certificate auth is enabled but trusted CA bundle is not configured in FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM.",
        )
    if trusted_cas and not _verify_cert_chained_to_trusted_cas(cert, trusted_cas):
        raise HTTPException(status_code=401, detail="Device client certificate was not issued by the configured trusted CA chain.")

    return DeviceCaller(
        thumbprint=thumbprint,
        subject_cn=subject_cn,
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
