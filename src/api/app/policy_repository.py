from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential
import yaml

from .models import PolicyDocument, PolicyStatus, PolicySummary, PolicyValidation

DEFAULT_POLICY_ID = "farsight-tool-policy"
DEFAULT_POLICY_VERSION = "2026-06-12.1"
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "policies" / "farsight-tool-policy.yaml"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_policy_content(content: str) -> PolicyValidation:
    messages: list[str] = []
    try:
        policy = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return PolicyValidation(status="invalid", messages=[f"YAML parse error: {exc}"])

    if not isinstance(policy, dict):
        return PolicyValidation(status="invalid", messages=["Policy must be a YAML object."])

    if policy.get("apiVersion") != "governance.toolkit/v1":
        messages.append("apiVersion must be governance.toolkit/v1.")
    if not policy.get("name"):
        messages.append("name is required.")
    if policy.get("default_action") not in {"allow", "deny", "require_approval"}:
        messages.append("default_action must be allow, deny, or require_approval.")
    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        messages.append("rules must contain at least one rule.")
    else:
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                messages.append(f"rules[{index}] must be an object.")
                continue
            if not rule.get("name"):
                messages.append(f"rules[{index}].name is required.")
            if not rule.get("condition"):
                messages.append(f"rules[{index}].condition is required.")
            if rule.get("action") not in {"allow", "deny", "require_approval"}:
                messages.append(f"rules[{index}].action must be allow, deny, or require_approval.")

    rule_text = "\n".join(str(rule) for rule in rules or [])
    if "contains_dangerous_input" not in rule_text:
        messages.append("Policy should include a contains_dangerous_input guard.")
    if "sensitive-diagnostic" not in rule_text:
        messages.append("Policy should define behavior for sensitive-diagnostic risk.")

    return PolicyValidation(status="valid" if not messages else "invalid", messages=messages)


class PolicyRepository:
    def list(self) -> list[PolicySummary]:
        raise NotImplementedError

    def get(self, policy_id: str, version: str | None = None) -> PolicyDocument:
        raise NotImplementedError

    def upsert(self, policy_id: str, version: str, content: str, status: PolicyStatus, actor: str, notes: str | None = None) -> PolicyDocument:
        raise NotImplementedError

    def activate(self, policy_id: str, version: str, actor: str, notes: str | None = None) -> PolicyDocument:
        raise NotImplementedError


class InMemoryPolicyRepository(PolicyRepository):
    def __init__(self) -> None:
        seed_content = DEFAULT_POLICY_PATH.read_text(encoding="utf-8") if DEFAULT_POLICY_PATH.exists() else _fallback_policy()
        now = utc_now()
        seed = PolicyDocument(
            id=f"{DEFAULT_POLICY_ID}:{DEFAULT_POLICY_VERSION}",
            policyId=DEFAULT_POLICY_ID,
            version=DEFAULT_POLICY_VERSION,
            status=PolicyStatus.active,
            content=seed_content,
            contentHash=content_hash(seed_content),
            createdAtUtc=now,
            createdBy="seed",
            updatedAtUtc=now,
            updatedBy="seed",
            activatedAtUtc=now,
            activatedBy="seed",
            notes="Seeded from bundled gateway policy.",
            validation=validate_policy_content(seed_content),
        )
        self._documents: dict[str, dict[str, PolicyDocument]] = {DEFAULT_POLICY_ID: {DEFAULT_POLICY_VERSION: seed}}

    def list(self) -> list[PolicySummary]:
        summaries: list[PolicySummary] = []
        for policy_id, versions in sorted(self._documents.items()):
            docs = sorted(versions.values(), key=lambda item: item.updated_at_utc, reverse=True)
            active = next((doc.version for doc in docs if doc.status == PolicyStatus.active), None)
            summaries.append(PolicySummary(policyId=policy_id, activeVersion=active, versions=docs))
        return summaries

    def get(self, policy_id: str, version: str | None = None) -> PolicyDocument:
        versions = self._documents.get(policy_id)
        if not versions:
            raise KeyError(policy_id)
        if version:
            doc = versions.get(version)
            if doc is None:
                raise KeyError(f"{policy_id}:{version}")
            return doc
        active = next((doc for doc in versions.values() if doc.status == PolicyStatus.active), None)
        if active is None:
            raise KeyError(f"{policy_id}:active")
        return active

    def upsert(self, policy_id: str, version: str, content: str, status: PolicyStatus, actor: str, notes: str | None = None) -> PolicyDocument:
        if status != PolicyStatus.draft:
            raise ValueError("Policy versions must be saved as draft. Use activate() to change the active version.")
        now = utc_now()
        existing = self._documents.get(policy_id, {}).get(version)
        created_at = existing.created_at_utc if existing else now
        created_by = existing.created_by if existing else actor
        doc = PolicyDocument(
            id=f"{policy_id}:{version}",
            policyId=policy_id,
            version=version,
            status=status,
            content=content,
            contentHash=content_hash(content),
            createdAtUtc=created_at,
            createdBy=created_by,
            updatedAtUtc=now,
            updatedBy=actor,
            activatedAtUtc=existing.activated_at_utc if existing else None,
            activatedBy=existing.activated_by if existing else None,
            notes=notes,
            validation=validate_policy_content(content),
        )
        self._documents.setdefault(policy_id, {})[version] = doc
        return doc

    def activate(self, policy_id: str, version: str, actor: str, notes: str | None = None) -> PolicyDocument:
        doc = self.get(policy_id, version)
        if doc.validation.status != "valid":
            raise ValueError("Cannot activate an invalid policy.")
        now = utc_now()
        versions = self._documents[policy_id]
        for existing_version, existing_doc in list(versions.items()):
            if existing_doc.status == PolicyStatus.active and existing_doc.version != version:
                versions[existing_version] = existing_doc.model_copy(update={"status": PolicyStatus.archived, "updated_at_utc": now, "updated_by": actor})
        activated = doc.model_copy(update={"status": PolicyStatus.active, "activated_at_utc": now, "activated_by": actor, "updated_at_utc": now, "updated_by": actor, "notes": notes or doc.notes})
        versions[version] = activated
        return activated


def _fallback_policy() -> str:
    return """apiVersion: governance.toolkit/v1
name: farsight-tool-policy
version: "2026-06-12.1"
default_action: deny
rules:
  - name: allow-read-only-lookups
    condition: "tool_name in ['get_job_status']"
    action: allow
"""


class CosmosPolicyRepository(PolicyRepository):
    """Cosmos-backed policy repository placeholder.

    The container already exists in infrastructure with partition key `/policyId`.
    Wire this implementation through dependencies once API identity/RBAC and
    Cosmos endpoint configuration are finalized.
    """

    def __init__(self, endpoint: str, credential: Any, database_name: str = "farsight", container_name: str = "policies") -> None:
        from azure.cosmos import CosmosClient

        client = CosmosClient(endpoint, credential=credential)
        self.container = client.get_database_client(database_name).get_container_client(container_name)
        self._ensure_seed_policy()

    def _seed_document(self) -> PolicyDocument:
        seed_content = DEFAULT_POLICY_PATH.read_text(encoding="utf-8") if DEFAULT_POLICY_PATH.exists() else _fallback_policy()
        now = utc_now()
        return PolicyDocument(
            id=f"{DEFAULT_POLICY_ID}:{DEFAULT_POLICY_VERSION}",
            policyId=DEFAULT_POLICY_ID,
            version=DEFAULT_POLICY_VERSION,
            status=PolicyStatus.active,
            content=seed_content,
            contentHash=content_hash(seed_content),
            createdAtUtc=now,
            createdBy="seed",
            updatedAtUtc=now,
            updatedBy="seed",
            activatedAtUtc=now,
            activatedBy="seed",
            notes="Seeded from bundled gateway policy.",
            validation=validate_policy_content(seed_content),
        )

    def _ensure_seed_policy(self) -> None:
        seed = self._seed_document()
        try:
            existing = self.get(DEFAULT_POLICY_ID, DEFAULT_POLICY_VERSION)
        except KeyError:
            self.container.upsert_item(seed.model_dump(by_alias=True, mode="json"))
            return

        if existing.created_by == "seed" and existing.content_hash != seed.content_hash:
            self.container.upsert_item(seed.model_dump(by_alias=True, mode="json"))

    def list(self) -> list[PolicySummary]:
        items = list(self.container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))
        grouped: dict[str, dict[str, PolicyDocument]] = {}
        for item in items:
            doc = PolicyDocument.model_validate(item)
            grouped.setdefault(doc.policy_id, {})[doc.version] = doc
        summaries: list[PolicySummary] = []
        for policy_id, versions in sorted(grouped.items()):
            docs = sorted(versions.values(), key=lambda item: item.updated_at_utc, reverse=True)
            active = next((doc.version for doc in docs if doc.status == PolicyStatus.active), None)
            summaries.append(PolicySummary(policyId=policy_id, activeVersion=active, versions=docs))
        return summaries

    def get(self, policy_id: str, version: str | None = None) -> PolicyDocument:
        if version:
            try:
                item = self.container.read_item(item=f"{policy_id}:{version}", partition_key=policy_id)
                return PolicyDocument.model_validate(item)
            except Exception as exc:
                if exc.__class__.__name__ == "CosmosResourceNotFoundError":
                    raise KeyError(f"{policy_id}:{version}") from exc
                raise
        items = list(self.container.query_items(
            query="SELECT * FROM c WHERE c.policyId = @policyId AND c.status = 'active'",
            parameters=[{"name": "@policyId", "value": policy_id}],
            partition_key=policy_id,
        ))
        if not items:
            raise KeyError(f"{policy_id}:active")
        return PolicyDocument.model_validate(items[0])

    def upsert(self, policy_id: str, version: str, content: str, status: PolicyStatus, actor: str, notes: str | None = None) -> PolicyDocument:
        if status != PolicyStatus.draft:
            raise ValueError("Policy versions must be saved as draft. Use activate() to change the active version.")
        now = utc_now()
        try:
            existing = self.get(policy_id, version)
            created_at = existing.created_at_utc
            created_by = existing.created_by
            activated_at = existing.activated_at_utc
            activated_by = existing.activated_by
        except KeyError:
            created_at = now
            created_by = actor
            activated_at = None
            activated_by = None
        doc = PolicyDocument(
            id=f"{policy_id}:{version}",
            policyId=policy_id,
            version=version,
            status=status,
            content=content,
            contentHash=content_hash(content),
            createdAtUtc=created_at,
            createdBy=created_by,
            updatedAtUtc=now,
            updatedBy=actor,
            activatedAtUtc=activated_at,
            activatedBy=activated_by,
            notes=notes,
            validation=validate_policy_content(content),
        )
        self.container.upsert_item(doc.model_dump(by_alias=True, mode="json"))
        return doc

    def activate(self, policy_id: str, version: str, actor: str, notes: str | None = None) -> PolicyDocument:
        doc = self.get(policy_id, version)
        if doc.validation.status != "valid":
            raise ValueError("Cannot activate an invalid policy.")
        now = utc_now()
        for summary in self.list():
            if summary.policy_id != policy_id:
                continue
            for existing in summary.versions:
                if existing.status == PolicyStatus.active and existing.version != version:
                    archived = existing.model_copy(update={"status": PolicyStatus.archived, "updated_at_utc": now, "updated_by": actor})
                    self.container.upsert_item(archived.model_dump(by_alias=True, mode="json"))
        activated = doc.model_copy(update={"status": PolicyStatus.active, "activated_at_utc": now, "activated_by": actor, "updated_at_utc": now, "updated_by": actor, "notes": notes or doc.notes})
        self.container.upsert_item(activated.model_dump(by_alias=True, mode="json"))
        return activated


_in_memory_policy_repository = InMemoryPolicyRepository()
_cosmos_policy_repository: CosmosPolicyRepository | None = None


def get_policy_repository() -> PolicyRepository:
    """Return the configured policy repository.

    Production deployments should set `FARSIGHT_COSMOS_ENDPOINT` so policy
    documents are stored in the Cosmos DB `policies` container. Local developer
    runs without that setting use the seeded in-memory repository.
    """

    global _cosmos_policy_repository

    endpoint = os.getenv("FARSIGHT_COSMOS_ENDPOINT", "").strip()
    if not endpoint:
        return _in_memory_policy_repository

    if _cosmos_policy_repository is None:
        _cosmos_policy_repository = CosmosPolicyRepository(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
            database_name=os.getenv("FARSIGHT_COSMOS_DATABASE", "farsight"),
            container_name=os.getenv("FARSIGHT_COSMOS_POLICIES_CONTAINER", "policies"),
        )
    return _cosmos_policy_repository
