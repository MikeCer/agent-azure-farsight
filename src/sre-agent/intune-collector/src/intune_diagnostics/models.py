from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import json

from .config import HARDWARE_FIELDS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_graph_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class Evidence:
    source: str
    field: str
    value: Any
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"source": self.source, "field": self.field, "value": self.value}
        if self.detail:
            data["detail"] = self.detail
        return data


@dataclass
class Finding:
    id: str
    severity: str
    confidence: str
    title: str
    description: str
    evidence: list[Evidence] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "confidence": self.confidence,
            "title": self.title,
            "description": self.description,
            "evidence": [item.to_dict() for item in self.evidence],
            "recommended_actions": self.recommended_actions,
        }


@dataclass
class EndpointResult:
    name: str
    method: str
    url: str
    api_version: str
    status: str
    http_status: int | None = None
    record_count: int = 0
    warning: str | None = None
    beta: bool = False
    next_link_followed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "api_version": self.api_version,
            "status": self.status,
            "http_status": self.http_status,
            "record_count": self.record_count,
            "warning": self.warning,
            "beta": self.beta,
            "next_link_followed": self.next_link_followed,
        }


@dataclass
class Target:
    input_device_name: str
    resolved_managed_device_id: str | None = None
    device_name: str | None = None
    azure_ad_device_id: str | None = None
    user_principal_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_device_name": self.input_device_name,
            "resolved_managed_device_id": self.resolved_managed_device_id,
            "device_name": self.device_name,
            "azure_ad_device_id": self.azure_ad_device_id,
            "user_principal_name": self.user_principal_name,
        }


@dataclass
class DiagnosticDocument:
    target: Target
    started_at: str
    completed_at: str | None = None
    tenant_id: str | None = None
    graph_profile: str = "v1.0+beta-endpoint-analytics"
    warnings: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    collection_report: list[EndpointResult] = field(default_factory=list)
    requested_sections: tuple[str, ...] = ("full",)

    def to_dict(self) -> dict[str, Any]:
        return self.to_sre_dict()

    def to_sre_dict(self) -> dict[str, Any]:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
        findings = sorted(self.findings, key=lambda item: (severity_order.get(item.severity, 99), item.id))
        compact_findings = [_compact_finding(item) for item in findings]
        diagnostic_evidence = _diagnostic_evidence(self.signals)
        if self.requested_sections != ("full",):
            health = diagnostic_evidence.get("device_health", {})
            for section, fields in HARDWARE_FIELDS.items():
                if section in self.requested_sections:
                    diagnostic_evidence[section] = {name: health.get(name) for name in fields}
                    if section == "memory":
                        diagnostic_evidence[section]["freeMemoryInBytes"] = None
                    if section == "storage" and "freeStoragePercent" in health:
                        diagnostic_evidence[section]["freeStoragePercent"] = health["freeStoragePercent"]
            diagnostic_evidence = {
                name: value for name, value in diagnostic_evidence.items() if name in self.requested_sections
            }
        return {
            "schema_version": "1.0",
            "target": self.target.to_dict(),
            "assessment": {
                "generated_at": self.completed_at,
                "highest_severity": compact_findings[0]["severity"] if compact_findings else "informational",
                "issue_count": len(compact_findings),
                "performance_status": _performance_status(diagnostic_evidence.get("performance", {})),
                "top_concerns": [item["title"] for item in compact_findings[:5]],
            },
            "issues": compact_findings,
            "diagnostic_evidence": diagnostic_evidence,
            "collection_scope": {
                "mode": "full" if self.requested_sections == ("full",) else "targeted",
                "requested_sections": list(self.requested_sections),
                "assessment_scope": "Only collected evidence was assessed; omitted sections are not healthy by implication.",
            },
            "data_gaps": _compact_data_gaps(self.collection_report, self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_sre_dict(), indent=2, sort_keys=True, default=str) + "\n"


def redact(value: Any, include_pii: bool) -> Any:
    if include_pii or value in (None, ""):
        return value
    return "redacted"


_BAD_STATE_TOKENS = {
    "attentionrequired",
    "blocked",
    "conflict",
    "disabled",
    "error",
    "failed",
    "failure",
    "noncompliant",
    "notinstalled",
    "outofdate",
    "paused",
    "remediationfailed",
    "unhealthy",
}

_COMPACT_FIELDS = [
    "id",
    "displayName",
    "name",
    "parentDisplayName",
    "policyObjectDisplayName",
    "setting",
    "settingName",
    "state",
    "status",
    "complianceStatus",
    "installState",
    "InstallState",
    "InstallStateDetail",
    "AppName",
    "AppVersion",
    "errorCode",
    "ErrorCode",
    "errorDescription",
    "lastModifiedDateTime",
    "LastModifiedDateTime",
    "lastSyncDateTime",
    "lastReportedDateTime",
    "deviceState",
    "productStatus",
    "malwareProtectionEnabled",
    "realTimeProtectionEnabled",
    "tamperProtectionEnabled",
    "signatureUpdateOverdue",
    "rebootRequired",
    "healthScore",
    "startupDuration",
    "bootTimeInMs",
    "crashCount",
    "hangCount",
    "failureCount",
]


def _compact_finding(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "title": finding.title,
        "description": finding.description,
        "evidence": [
            compact
            for compact in (_compact_evidence(item) for item in finding.evidence)
            if compact["value"] not in (None, "", [], {})
        ],
        "recommended_actions": finding.recommended_actions,
    }


def _compact_evidence(evidence: Evidence) -> dict[str, Any]:
    data = {
        "source": evidence.source,
        "field": evidence.field,
        "value": _compact_value(evidence.value),
    }
    if evidence.detail:
        data["detail"] = evidence.detail
    return data


def _diagnostic_evidence(signals: dict[str, Any]) -> dict[str, Any]:
    inventory = signals.get("inventory") or {}
    device_health_detail = signals.get("device_health_detail") or {}
    security = signals.get("security") or {}
    identity = signals.get("identity") or {}
    management = signals.get("management") or {}
    updates = signals.get("updates") or {}
    endpoint_analytics = signals.get("endpoint_analytics") or {}
    events = signals.get("events") or {}
    return _drop_empty(
        {
            "device": _compact_record(
                inventory,
                [
                    "deviceName",
                    "operatingSystem",
                    "osVersion",
                    "manufacturer",
                    "model",
                    "complianceState",
                    "managementState",
                    "lastSyncDateTime",
                    "enrolledDateTime",
                    "hardwareInformation",
                ],
            ),
            "device_health": _device_health_evidence(device_health_detail),
            "performance": _performance_evidence(endpoint_analytics),
            "installed_applications": _installed_applications(signals.get("installed_apps") or []),
            "app_crashes": _app_crash_evidence(endpoint_analytics),
            "recent_restart_shutdown_events": _event_list(events.get("recent_restart_shutdown_events") or []),
            "device_timeline_events": _event_list(events.get("device_timeline_events") or []),
            "policy_and_configuration_issues": _limit(
                _dedupe_by_identity(
                    [
                        *_problem_records(signals.get("compliance") or []),
                        *_problem_records(signals.get("compliance_setting_states") or []),
                        *_problem_records(signals.get("configuration") or []),
                        *_problem_records(signals.get("configuration_setting_states") or []),
                        *_problem_records(security.get("endpoint_security_intent_device_states") or []),
                    ]
                ),
                10,
            ),
            "app_installation_issues": _limit(_problem_records(signals.get("app_install_status") or []), 10),
            "security_issues": _risk_fields(security.get("windows_protection_state") or {}),
            "windows_update_issues": _limit(_problem_records(updates.get("windows_update_status") or []), 10),
            "management_failures": _limit(
                _problem_records(
                    [
                        *(management.get("device_action_results") or []),
                        *(management.get("remediation_script_states") or []),
                    ]
                ),
                10,
            ),
            "identity_issues": _identity_issues(identity),
            "troubleshooting_errors": _limit(_problem_records(signals.get("troubleshooting_events") or []), 10),
        }
    )


def _device_health_evidence(health: dict[str, Any]) -> dict[str, Any]:
    evidence = _compact_record(
        health,
        [
            "isEncrypted",
            "totalStorageSpaceInBytes",
            "freeStorageSpaceInBytes",
            "physicalMemoryInBytes",
            "processorArchitecture",
            "complianceGracePeriodExpirationDateTime",
            "managementCertificateExpirationDate",
            "windowsActiveMalwareCount",
            "windowsRemediatedMalwareCount",
            "usersLoggedOn",
        ],
    )
    total = _as_number(evidence.get("totalStorageSpaceInBytes"))
    free = _as_number(evidence.get("freeStorageSpaceInBytes"))
    if total and free is not None:
        evidence["freeStoragePercent"] = round((free / total) * 100, 1)
    return evidence


def _compact_data_gaps(results: list[EndpointResult], warnings: list[str]) -> list[dict[str, Any]]:
    gaps: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.status not in {"failed", "skipped"}:
            continue
        reason = _short_reason(result.warning)
        if result.status == "skipped" and reason and "No parent state ids" in reason:
            continue
        gap = gaps.setdefault(
            result.name,
            {
                "source": result.name,
                "status": result.status,
                "api_version": result.api_version,
                "reason": reason,
                "occurrences": 0,
            },
        )
        gap["occurrences"] += 1
    for warning in warnings:
        name, _, reason = warning.partition(":")
        if not name or name in gaps:
            continue
        gaps[name] = {"source": name, "status": "warning", "reason": _short_reason(reason), "occurrences": 1}
    return sorted(gaps.values(), key=lambda item: item["source"])


def _compact_endpoint_analytics(endpoint_analytics: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for name, records in endpoint_analytics.items():
        if not records:
            continue
        problems = _problem_records(records)
        compact[name] = _limit(problems or [_compact_record(record) for record in records])
    return compact


def _performance_evidence(endpoint_analytics: dict[str, Any]) -> dict[str, Any]:
    device_perf = _first(endpoint_analytics.get("device_performance") or [])
    app_health = _first(endpoint_analytics.get("app_health_device_performance") or [])
    resource_perf = _first(endpoint_analytics.get("resource_performance") or [])
    return _drop_empty(
        {
            "startup": _compact_record(
                device_perf,
                [
                    "healthStatus",
                    "startupPerformanceScore",
                    "bootScore",
                    "loginScore",
                    "coreBootTimeInMs",
                    "coreLoginTimeInMs",
                    "groupPolicyBootTimeInMs",
                    "groupPolicyLoginTimeInMs",
                    "responsiveDesktopTimeInMs",
                    "restartCount",
                    "averageRestarts",
                    "blueScreenCount",
                    "averageBlueScreens",
                    "diskType",
                ],
            ),
            "resource": _compact_record(
                resource_perf,
                [
                    "healthStatus",
                    "deviceResourcePerformanceScore",
                    "averageSpikeTimeScore",
                    "cpuSpikeTimeScore",
                    "cpuSpikeTimePercentage",
                    "cpuSpikeTimePercentageThreshold",
                    "ramSpikeTimeScore",
                    "ramSpikeTimePercentage",
                    "ramSpikeTimePercentageThreshold",
                    "totalRamInMB",
                    "totalProcessorCoreCount",
                    "cpuDisplayName",
                    "cpuClockSpeedInMHz",
                    "diskType",
                    "machineType",
                ],
            ),
            "app_reliability": _compact_record(
                app_health,
                [
                    "healthStatus",
                    "deviceAppHealthStatus",
                    "deviceAppHealthScore",
                    "crashedAppCount",
                    "appCrashCount",
                    "appHangCount",
                    "meanTimeToFailureInMinutes",
                    "processedDateTime",
                ],
            ),
        }
    )


def _installed_applications(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = []
    for record in records:
        app = _compact_record(
            record,
            [
                "displayName",
                "version",
                "publisher",
            ],
        )
        if app:
            apps.append(app)
    return _limit(sorted(apps, key=lambda item: str(item.get("displayName") or item.get("appName") or "").casefold()), 150)


def _app_crash_evidence(endpoint_analytics: dict[str, Any]) -> dict[str, Any]:
    device_summary = _compact_record(
        _first(endpoint_analytics.get("app_health_device_performance") or []),
        [
            "healthStatus",
            "deviceAppHealthStatus",
            "deviceAppHealthScore",
            "crashedAppCount",
            "appCrashCount",
            "appHangCount",
            "meanTimeToFailureInMinutes",
            "processedDateTime",
        ],
    )
    crashing_apps = [
        _compact_record(
            item,
            [
                "appDisplayName",
                "appName",
                "appVersion",
                "appPublisher",
                "appHealthScore",
                "appHealthStatus",
                "appCrashCount",
                "appHangCount",
                "meanTimeToFailureInMinutes",
                "activeDeviceCount",
            ],
        )
        for item in endpoint_analytics.get("app_crashes") or []
    ]
    output = {"crashing_applications": _limit(crashing_apps, 50)}
    if device_summary:
        output["device_summary"] = device_summary
    return output


def _event_list(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _limit(
        [
            _compact_record(
                record,
                [
                    "source",
                    "eventType",
                    "actionName",
                    "state",
                    "status",
                    "activity",
                    "activityType",
                    "activityResult",
                    "category",
                    "actor",
                    "message",
                    "errorCode",
                    "startDateTime",
                    "lastUpdatedDateTime",
                    "eventDateTime",
                    "activityDateTime",
                ],
            )
            for record in records
        ],
        25,
    )


def _performance_status(performance: dict[str, Any]) -> str:
    if not performance:
        return "not_available"
    flattened = _flatten(performance)
    bad_health = [
        value
        for key, value in flattened.items()
        if key.lower().endswith("healthstatus") and str(value).lower() in {"needsattention", "unhealthy", "poor"}
    ]
    low_scores = [
        value
        for key, value in flattened.items()
        if "score" in key.lower() and isinstance(value, (int, float)) and value < 50
    ]
    crash_counts = [
        value
        for key, value in flattened.items()
        if any(token in key.lower() for token in ["crash", "hang", "bluescreen"])
        and isinstance(value, (int, float))
        and value > 0
    ]
    if bad_health or low_scores or crash_counts:
        return "needs_attention"
    return "healthy"


def _first(records: list[dict[str, Any]]) -> dict[str, Any]:
    return records[0] if records else {}


def _problem_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_compact_record(record) for record in records if _is_problem_record(record)]


def _is_problem_record(record: dict[str, Any]) -> bool:
    flattened = _flatten(record)
    for key, value in flattened.items():
        lowered_key = key.lower()
        normalized_value = str(value).replace(" ", "").lower()
        if lowered_key.endswith("errorcode") and value not in (None, "", 0, "0", "No error code"):
            return True
        if any(token in lowered_key for token in ["state", "status", "result", "error"]):
            if normalized_value in _BAD_STATE_TOKENS:
                return True
    return False


def _risk_fields(record: dict[str, Any]) -> dict[str, Any]:
    flattened = _flatten(record)
    risks: dict[str, Any] = {}
    risky_false_fields = {
        "defenderEnabled",
        "malwareProtectionEnabled",
        "networkInspectionSystemEnabled",
        "realTimeProtectionEnabled",
        "tamperProtectionEnabled",
    }
    risky_true_fields = {
        "fullScanOverdue",
        "fullScanRequired",
        "quickScanOverdue",
        "rebootRequired",
        "signatureUpdateOverdue",
    }
    for key, value in flattened.items():
        field_name = key.split(".")[-1]
        normalized = str(value).replace(" ", "").lower()
        if field_name in risky_false_fields and value is False:
            risks[key] = value
        elif field_name in risky_true_fields and value is True:
            risks[key] = value
        elif normalized in {"disabled", "unhealthy", "outofdate", "error"}:
            risks[key] = value
    return risks


def _identity_issues(identity: dict[str, Any]) -> dict[str, Any]:
    entra = identity.get("entra_device") or {}
    issues: dict[str, Any] = {}
    if entra.get("accountEnabled") is False:
        issues["accountEnabled"] = False
    if entra.get("isManaged") is False:
        issues["isManaged"] = False
    if entra.get("isCompliant") is False:
        issues["isCompliant"] = False
    if issues:
        issues["displayName"] = entra.get("displayName")
        issues["trustType"] = entra.get("trustType")
        issues["approximateLastSignInDateTime"] = entra.get("approximateLastSignInDateTime")
    return _drop_empty(issues)


def _compact_value(value: Any) -> Any:
    if isinstance(value, list):
        return _limit([_compact_value(item) for item in value])
    if isinstance(value, dict):
        return _compact_record(value)
    return value


def _compact_record(record: dict[str, Any], fields: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"value": record}
    selected = fields or _COMPACT_FIELDS
    compact: dict[str, Any] = {}
    for field_name in selected:
        if field_name in record and record[field_name] not in (None, "", [], {}):
            value = record[field_name]
            if isinstance(value, dict):
                compact[field_name] = _compact_nested_dict(value)
            elif isinstance(value, list):
                compact[field_name] = _limit([_compact_value(item) for item in value])
            else:
                compact[field_name] = value
    if not compact:
        for key, value in record.items():
            if key.startswith("@odata") or value in (None, "", [], {}):
                continue
            if len(compact) >= 8:
                break
            compact[key] = _compact_value(value) if isinstance(value, (dict, list)) else value
    return compact


def _compact_nested_dict(value: dict[str, Any]) -> dict[str, Any]:
    preferred = [
        "systemMemoryInGB",
        "storageCapacityInGB",
        "totalStorageSpaceInBytes",
        "freeStorageSpaceInBytes",
        "tpmSpecificationVersion",
        "isEncrypted",
    ]
    compact = {key: value[key] for key in preferred if key in value and value[key] not in (None, "", [], {})}
    return compact or {
        key: nested for key, nested in value.items() if not key.startswith("@odata") and nested not in (None, "", [], {})
    }


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, nested in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(nested, child_prefix))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            result.update(_flatten(nested, f"{prefix}[{index}]"))
    else:
        result[prefix] = value
    return result


def _limit(items: list[Any], max_items: int = 20) -> list[Any]:
    deduped: list[Any] = []
    seen: set[str] = set()
    for item in items:
        marker = json.dumps(item, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def _dedupe_by_identity(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = "|".join(
            str(item.get(field, ""))
            for field in ["parentDisplayName", "policyObjectDisplayName", "displayName", "setting", "settingName", "state"]
        )
        best_by_key.setdefault(key, item)
    return list(best_by_key.values())


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _short_reason(value: str | None, max_length: int = 240) -> str:
    if not value:
        return ""
    collapsed = " ".join(str(value).split())
    if "HTTP 403" in collapsed:
        return "Missing Microsoft Graph permission or admin consent for this source."
    if "HTTP 401" in collapsed:
        return "Authentication failed for Microsoft Graph."
    if "Resource not found for the segment" in collapsed:
        return "This Graph source is not available in the current tenant/API profile."
    if "Invalid filter clause" in collapsed and "Could not find a property named" in collapsed:
        return "This Graph source does not support the per-device filter shape used by the collector."
    if "Parsing OData Select and Expand failed" in collapsed:
        return "This Graph source does not support the requested select/expand shape."
    return collapsed if len(collapsed) <= max_length else f"{collapsed[: max_length - 3]}..."


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None
