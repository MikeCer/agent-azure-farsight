from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import DiagnosticConfig
from .models import Evidence, Finding, parse_graph_datetime


def evaluate(signals: dict[str, Any], config: DiagnosticConfig) -> list[Finding]:
    findings: list[Finding] = []
    inventory = signals.get("inventory") or {}
    findings.extend(_check_stale_checkin(inventory, config))
    findings.extend(_check_device_health_detail(signals.get("device_health_detail") or {}, config))
    findings.extend(_check_compliance(inventory, signals.get("compliance") or []))
    findings.extend(
        _check_setting_level_failures(
            signals.get("compliance_setting_states") or [],
            signals.get("configuration_setting_states") or [],
            signals.get("security", {}).get("endpoint_security_intent_device_states") or [],
        )
    )
    findings.extend(_check_app_install_status(signals.get("app_install_status") or []))
    findings.extend(_check_update_status(signals.get("updates") or {}))
    findings.extend(_check_management_actions(signals.get("management") or {}))
    findings.extend(_check_identity_state(signals.get("identity") or {}))
    findings.extend(_check_health_attestation(signals.get("health_attestation") or {}))
    findings.extend(_check_windows_protection(signals.get("security", {}).get("windows_protection_state") or {}))
    findings.extend(_check_troubleshooting(signals.get("troubleshooting_events") or [], config))
    findings.extend(_check_endpoint_analytics(signals.get("endpoint_analytics") or {}, config))
    findings.extend(_check_hardware(inventory, config))
    return findings


def resolution_error_finding(
    kind: str,
    message: str,
    candidates: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> Finding:
    severity = "critical" if kind in {"not_found", "ambiguous"} else "high"
    evidence = [Evidence("device_resolution", "error", kind, message)]
    if details:
        evidence.append(Evidence("device_resolution", "graph_error_details", details))
    if candidates:
        evidence.append(Evidence("device_resolution", "candidates", candidates))
    title = {
        "not_found": "Device was not found in Intune",
        "ambiguous": "Multiple matching Intune devices were found",
        "authorization_error": "Intune device lookup failed because Graph access was denied",
        "endpoint_not_found": "Intune device lookup endpoint was not available",
        "collection_error": "Intune device lookup failed",
        "invalid_input": "Invalid device lookup input",
    }.get(kind, "Intune device lookup failed")
    actions = {
        "authorization_error": [
            "Verify the tool is using credentials for the Intune tenant, not the SRE Agent tenant.",
            "Grant Microsoft Graph application permission DeviceManagementManagedDevices.Read.All to the service principal or managed identity used by the tool.",
            "Grant tenant-wide admin consent for the Graph permissions and retry after propagation.",
        ],
        "not_found": [
            "Confirm the Windows client is enrolled in Intune and has checked in recently.",
            "Verify the deviceName is exact, including prefixes, suffixes, and casing used in Intune.",
        ],
        "ambiguous": [
            "Rerun with an optional managed device id, Entra device id, or serial-number disambiguator.",
            "Review duplicate Intune records and retire stale records if appropriate.",
        ],
    }.get(
        kind,
        [
            "Review the Graph error details in this finding.",
            "Confirm the Intune tenant, Graph permissions, and service availability before retrying.",
        ],
    )
    return Finding(
        id=f"device-resolution-{kind}",
        severity=severity,
        confidence="high",
        title=title,
        description=message,
        evidence=evidence,
        recommended_actions=actions,
    )


def _check_stale_checkin(inventory: dict[str, Any], config: DiagnosticConfig) -> list[Finding]:
    last_sync = parse_graph_datetime(inventory.get("lastSyncDateTime"))
    if not last_sync:
        return []
    age_days = (datetime.now(timezone.utc) - last_sync).total_seconds() / 86400
    if age_days < config.stale_checkin_medium_days:
        return []
    severity = "high" if age_days >= config.stale_checkin_high_days else "medium"
    return [
        Finding(
            id="stale-intune-checkin",
            severity=severity,
            confidence="high",
            title="Device has a stale Intune check-in",
            description=f"The device last synchronized with Intune {age_days:.1f} days ago.",
            evidence=[Evidence("managed_device", "lastSyncDateTime", inventory.get("lastSyncDateTime"))],
            recommended_actions=[
                "Ask the user to connect to the corporate network or internet and trigger an Intune sync.",
                "Verify the Intune Management Extension and management channel from the Intune admin center.",
                "If the device is retired or re-enrolled, clean up stale Intune records before further diagnosis.",
            ],
        )
    ]


def _check_compliance(inventory: dict[str, Any], states: list[dict[str, Any]]) -> list[Finding]:
    compliance = str(inventory.get("complianceState") or "").lower()
    failed_states = [
        item
        for item in states
        if str(item.get("state") or item.get("complianceStatus") or "").lower()
        in {"noncompliant", "error", "conflict", "unknown"}
    ]
    if compliance in {"", "compliant"} and not failed_states:
        return []
    return [
        Finding(
            id="device-noncompliant",
            severity="high",
            confidence="high",
            title="Device is not compliant in Intune",
            description="Intune reports a non-compliant, error, conflict, or unknown compliance state.",
            evidence=[
                Evidence("managed_device", "complianceState", inventory.get("complianceState")),
                Evidence("deviceCompliancePolicyStates", "failedStates", failed_states),
            ],
            recommended_actions=[
                "Open the device in Intune and inspect failed compliance policies.",
                "Prioritize remediation of compliance settings marked error, conflict, or noncompliant.",
                "Confirm the device has received the latest compliance policy assignments.",
            ],
        )
    ]


def _check_device_health_detail(health: dict[str, Any], config: DiagnosticConfig) -> list[Finding]:
    findings: list[Finding] = []
    if health.get("isEncrypted") is False:
        findings.append(
            Finding(
                id="device-encryption-disabled",
                severity="high",
                confidence="high",
                title="Device encryption is reported as disabled",
                description="Intune beta managed-device detail reports isEncrypted=false, which supports the BitLocker noncompliance finding.",
                evidence=[Evidence("managed_device", "isEncrypted", False)],
                recommended_actions=[
                    "Verify BitLocker status in Intune and confirm whether encryption is intentionally disabled.",
                    "Check TPM/secure boot readiness and BitLocker policy assignment before triggering remediation.",
                    "If policy is correct, force an Intune sync and review encryption status after the device reports back.",
                ],
            )
        )

    total = _as_number(health.get("totalStorageSpaceInBytes"))
    free = _as_number(health.get("freeStorageSpaceInBytes"))
    if total and free is not None:
        free_percent = (free / total) * 100
        if free_percent < 10:
            findings.append(
                Finding(
                    id="low-free-disk-space",
                    severity="medium",
                    confidence="high",
                    title="Device has low free disk space",
                    description=f"Intune reports {free_percent:.1f}% free disk space.",
                    evidence=[
                        Evidence("managed_device", "totalStorageSpaceInBytes", health.get("totalStorageSpaceInBytes")),
                        Evidence("managed_device", "freeStorageSpaceInBytes", health.get("freeStorageSpaceInBytes")),
                    ],
                    recommended_actions=[
                        "Review storage usage and cleanup opportunities before investigating application or update failures.",
                        "Check whether Windows Update, Defender, or application installs are blocked by low disk space.",
                    ],
                )
            )
    return findings


def _check_health_attestation(attestation: dict[str, Any]) -> list[Finding]:
    if not attestation:
        return []
    bad_fields: dict[str, Any] = {}
    for key, value in _flatten(attestation).items():
        lowered = str(value).lower()
        if any(token in key.lower() for token in ["bitlocker", "secureboot", "codeintegrity", "tpm", "healthstatus"]):
            if lowered in {"false", "off", "disabled", "unhealthy", "notapplicable", "error", "unknown"}:
                bad_fields[key] = value
    if not bad_fields:
        return []
    return [
        Finding(
            id="health-attestation-risk",
            severity="high",
            confidence="medium",
            title="Device health attestation reports security posture risks",
            description="Intune health attestation contains disabled, unhealthy, error, or unknown security fields.",
            evidence=[Evidence("deviceHealthAttestationState", "riskFields", bad_fields)],
            recommended_actions=[
                "Review BitLocker, Secure Boot, TPM, and code integrity state from the Intune device blade.",
                "Confirm the device supports health attestation and has recently synchronized.",
                "Remediate failed security posture items through Intune policy or endpoint support workflow.",
            ],
        )
    ]


def _check_setting_level_failures(
    compliance_settings: list[dict[str, Any]],
    configuration_settings: list[dict[str, Any]],
    endpoint_security_states: list[dict[str, Any]],
) -> list[Finding]:
    failed = _failed_records([*compliance_settings, *configuration_settings, *endpoint_security_states])
    if not failed:
        return []
    return [
        Finding(
            id="setting-level-policy-failures",
            severity="high",
            confidence="medium",
            title="Policy setting-level failures are reported for the device",
            description="Intune setting-level data includes error, failed, conflict, or noncompliant states.",
            evidence=[Evidence("policy_setting_states", "failedRecords", failed[:20])],
            recommended_actions=[
                "Inspect the failed setting names and error codes in Intune before changing broad policies.",
                "Prioritize endpoint security and compliance setting failures that block access or reduce protection.",
                "Confirm the device has synced after the latest assignment or remediation.",
            ],
        )
    ]


def _check_app_install_status(records: list[dict[str, Any]]) -> list[Finding]:
    failed = _failed_records(records)
    if not failed:
        return []
    return [
        Finding(
            id="app-install-failures",
            severity="high",
            confidence="medium",
            title="Required app installation failures are reported",
            description="Intune app installation status contains failed/error records for the device.",
            evidence=[Evidence("device_install_status_report", "failedRecords", failed[:20])],
            recommended_actions=[
                "Review the failed app name, version, install state detail, and error code in Intune.",
                "Check app assignment targeting, detection rules, prerequisites, and supersedence/dependency chains.",
                "If this is a Win32 app, map the Intune error code to the installer log and remediation guidance.",
            ],
        )
    ]


def _check_update_status(updates: dict[str, Any]) -> list[Finding]:
    failed = _failed_records(updates.get("windows_update_status") or [])
    if not failed:
        return []
    return [
        Finding(
            id="windows-update-issues",
            severity="medium",
            confidence="medium",
            title="Windows update status indicates failures or attention is required",
            description="Intune Windows update status data includes failed, error, paused, blocked, or attention-required records.",
            evidence=[Evidence("windows_update_status", "problemRecords", failed[:20])],
            recommended_actions=[
                "Review Windows update policy assignment, deadline, safeguard, and reboot requirements in Intune.",
                "Confirm the device can reach Windows Update for Business and has recently synced.",
                "Prioritize quality update failures before feature update troubleshooting when both are present.",
            ],
        )
    ]


def _check_management_actions(management: dict[str, Any]) -> list[Finding]:
    records = [
        *(management.get("device_action_results") or []),
        *(management.get("remediation_script_states") or []),
    ]
    failed = _failed_records(records)
    if not failed:
        return []
    return [
        Finding(
            id="management-action-or-script-failures",
            severity="medium",
            confidence="medium",
            title="Management actions or Intune scripts report failures",
            description="Device action results, proactive remediations, or management script states include failed/error records.",
            evidence=[Evidence("management", "failedRecords", failed[:20])],
            recommended_actions=[
                "Review failed device actions and script/remediation run states in Intune.",
                "Correlate failures with management extension health, sync freshness, and assignment scope.",
            ],
        )
    ]


def _check_identity_state(identity: dict[str, Any]) -> list[Finding]:
    entra_device = identity.get("entra_device") or {}
    if entra_device.get("accountEnabled") is not False and str(entra_device.get("isCompliant", "")).lower() != "false":
        return []
    return [
        Finding(
            id="entra-device-identity-risk",
            severity="high",
            confidence="high",
            title="Entra device identity may block normal management or access",
            description="The Entra device object is disabled or marked noncompliant.",
            evidence=[
                Evidence("entra_device", "accountEnabled", entra_device.get("accountEnabled")),
                Evidence("entra_device", "isCompliant", entra_device.get("isCompliant")),
            ],
            recommended_actions=[
                "Verify the Entra device object is enabled and corresponds to the active Intune managed device.",
                "Check for duplicate/stale Entra device objects before remediating policy or app failures.",
            ],
        )
    ]


def _check_windows_protection(protection: dict[str, Any]) -> list[Finding]:
    if not protection:
        return []
    flattened = _flatten(protection)
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
    risky: dict[str, Any] = {}
    for key, value in flattened.items():
        field_name = key.split(".")[-1]
        lowered = str(value).replace(" ", "").lower()
        if field_name in risky_false_fields and value is False:
            risky[key] = value
        elif field_name in risky_true_fields and value is True:
            risky[key] = value
        elif lowered in {"disabled", "unhealthy", "outofdate", "error"}:
            risky[key] = value
    if not risky:
        return []
    return [
        Finding(
            id="windows-protection-risk",
            severity="high",
            confidence="medium",
            title="Windows protection state reports security risks",
            description="Intune Windows protection state contains disabled, unhealthy, out-of-date, error, or unknown security signals.",
            evidence=[Evidence("windowsProtectionState", "riskFields", risky)],
            recommended_actions=[
                "Review Defender, firewall, malware, and signature health in Intune.",
                "Confirm endpoint security policies are assigned and the device has synced recently.",
            ],
        )
    ]


def _check_troubleshooting(events: list[dict[str, Any]], config: DiagnosticConfig) -> list[Finding]:
    error_events = [
        event
        for event in events
        if any(str(event.get(field, "")).lower() in {"error", "failed", "failure"} for field in ["status", "eventType"])
        or event.get("errorCode")
    ]
    if not error_events:
        return []
    severity = "high" if len(error_events) >= config.troubleshooting_error_high_count else "medium"
    return [
        Finding(
            id="intune-troubleshooting-errors",
            severity=severity,
            confidence="medium",
            title="Recent Intune troubleshooting events include failures",
            description=f"Found {len(error_events)} troubleshooting event(s) that indicate errors or failures.",
            evidence=[Evidence("deviceManagementTroubleshootingEvents", "errorEvents", error_events[:10])],
            recommended_actions=[
                "Review Intune troubleshooting events for failed policy, app, or enrollment operations.",
                "Correlate the event timestamps with user-reported symptoms and recent policy/app changes.",
            ],
        )
    ]


def _check_endpoint_analytics(endpoint_analytics: dict[str, Any], config: DiagnosticConfig) -> list[Finding]:
    findings: list[Finding] = []
    flattened = _flatten(endpoint_analytics)
    poor_scores = {
        key: value
        for key, value in flattened.items()
        if "score" in key.lower() and _as_number(value) is not None and _as_number(value) <= config.poor_score_threshold
        and _as_number(value) >= 0
        and "model" not in key.lower()
    }
    slow_boot = {
        key: value
        for key, value in flattened.items()
        if any(token in key.lower() for token in ["boottime", "startupduration", "restarttime"])
        and _duration_seconds(value) is not None
        and _duration_seconds(value) >= config.slow_boot_seconds
    }
    crash_signals = {
        key: value
        for key, value in flattened.items()
        if any(token in key.lower() for token in ["crash", "hang", "fault"])
        and "meanTimeToFailure".lower() not in key.lower()
        and _as_number(value) is not None
        and _as_number(value) > 0
    }
    if poor_scores or slow_boot:
        findings.append(
            Finding(
                id="endpoint-analytics-performance",
                severity="medium",
                confidence="medium",
                title="Endpoint Analytics indicates performance bottlenecks",
                description="Beta Endpoint Analytics data contains low scores or slow startup indicators.",
                evidence=[
                    Evidence("endpoint_analytics", "poorScores", poor_scores),
                    Evidence("endpoint_analytics", "slowBootSignals", slow_boot),
                ],
                recommended_actions=[
                    "Review Endpoint Analytics startup performance and high-impact startup processes.",
                    "Prioritize disabling/remediating high-impact startup processes through Intune policy where appropriate.",
                    "Validate with the user after the device completes a fresh Intune sync.",
                ],
            )
        )
    if crash_signals:
        findings.append(
            Finding(
                id="endpoint-analytics-app-reliability",
                severity="medium",
                confidence="medium",
                title="Endpoint Analytics indicates app reliability issues",
                description="Beta Endpoint Analytics app health data contains crash, hang, fault, or failure signals.",
                evidence=[Evidence("endpoint_analytics", "crashSignals", crash_signals)],
                recommended_actions=[
                    "Identify the affected application and version in Endpoint Analytics app health.",
                    "Check whether a newer app version or rollback is available through Intune app deployment.",
                    "Correlate app reliability events with recent application assignments or updates.",
                ],
            )
        )
    return findings


def _check_hardware(inventory: dict[str, Any], config: DiagnosticConfig) -> list[Finding]:
    hardware = inventory.get("hardwareInformation") or {}
    memory = _as_number(hardware.get("systemMemoryInGB"))
    storage = _as_number(hardware.get("storageCapacityInGB"))
    bottlenecks: dict[str, Any] = {}
    if memory is not None and memory < config.low_memory_gb:
        bottlenecks["systemMemoryInGB"] = memory
    if storage is not None and storage < config.low_storage_capacity_gb:
        bottlenecks["storageCapacityInGB"] = storage
    if not bottlenecks:
        return []
    return [
        Finding(
            id="hardware-capacity-bottleneck",
            severity="medium",
            confidence="medium",
            title="Device hardware capacity may be a bottleneck",
            description="Intune hardware inventory reports memory or storage capacity below the configured threshold.",
            evidence=[Evidence("managed_device.hardwareInformation", "bottlenecks", bottlenecks)],
            recommended_actions=[
                "Confirm device model, memory, and storage capacity against the corporate Windows baseline.",
                "Prioritize hardware refresh or workload reduction for devices below baseline.",
            ],
        )
    ]


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


def _failed_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    bad_tokens = {
        "attentionrequired",
        "blocked",
        "conflict",
        "error",
        "failed",
        "failure",
        "noncompliant",
        "notinstalled",
        "paused",
        "remediationfailed",
        "unhealthy",
    }
    for record in records:
        flattened = _flatten(record)
        text_values = {str(value).replace(" ", "").lower() for value in flattened.values()}
        key_values = {
            str(value).replace(" ", "").lower()
            for key, value in flattened.items()
            if any(token in key.lower() for token in ["state", "status", "result", "error", "code"])
        }
        if bad_tokens & (text_values | key_values):
            failed.append(record)
            continue
        if any(key.lower().endswith("errorcode") and value not in (None, "", 0, "0") for key, value in flattened.items()):
            failed.append(record)
    return failed


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _duration_seconds(value: Any) -> float | None:
    number = _as_number(value)
    if number is None:
        return None
    return number / 1000 if number > 1000 else number
