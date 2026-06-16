from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from .config import DiagnosticConfig
from .graph_client import GraphError
from .models import DiagnosticDocument, EndpointResult, Target, redact, utc_now_iso
from .resolver import _azure_ad_device_id
from .rules import evaluate


class GraphCollectorClient(Protocol):
    def get(self, api_version: str, path_or_url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    def post(
        self,
        api_version: str,
        path_or_url: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def get_all(
        self,
        api_version: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        ...


@dataclass
class Collection:
    items: list[dict[str, Any]]
    result: EndpointResult


def collect_device_diagnostics(
    graph: GraphCollectorClient,
    managed_device: dict[str, Any],
    input_device_name: str,
    config: DiagnosticConfig,
    *,
    tenant_id: str | None = None,
) -> DiagnosticDocument:
    started_at = utc_now_iso()
    target = Target(
        input_device_name=input_device_name,
        resolved_managed_device_id=managed_device.get("id"),
        device_name=managed_device.get("deviceName"),
        azure_ad_device_id=_azure_ad_device_id(managed_device) or None,
        user_principal_name=redact(managed_device.get("userPrincipalName"), config.include_pii),
    )
    document = DiagnosticDocument(target=target, started_at=started_at, tenant_id=tenant_id)

    device_id = str(managed_device["id"])
    encoded_device_id = _path_segment(device_id)
    device_detail = _get_optional(
        graph,
        "managed_device",
        "v1.0",
        f"/deviceManagement/managedDevices/{encoded_device_id}",
    )
    device_health_detail = _collect_device_health_detail(graph, device_id)
    document.collection_report.append(device_detail.result)
    document.collection_report.append(device_health_detail.result)
    device = device_detail.items[0] if device_detail.items else managed_device

    compliance = _get_all_optional(
        graph,
        "device_compliance_policy_states",
        "v1.0",
        f"/deviceManagement/managedDevices/{encoded_device_id}/deviceCompliancePolicyStates",
        max_pages=config.max_optional_pages,
    )
    configuration = _get_all_optional(
        graph,
        "device_configuration_states",
        "v1.0",
        f"/deviceManagement/managedDevices/{encoded_device_id}/deviceConfigurationStates",
        max_pages=config.max_optional_pages,
    )
    compliance_setting_states, compliance_setting_reports = _collect_nested_setting_states(
        graph,
        "device_compliance_policy_setting_states",
        "v1.0",
        f"/deviceManagement/managedDevices/{encoded_device_id}/deviceCompliancePolicyStates",
        compliance.items,
        config,
    )
    configuration_setting_states, configuration_setting_reports = _collect_nested_setting_states(
        graph,
        "device_configuration_setting_states",
        "v1.0",
        f"/deviceManagement/managedDevices/{encoded_device_id}/deviceConfigurationStates",
        configuration.items,
        config,
    )
    installed_apps = _collect_installed_apps(graph, device_id, config)
    app_install_status = _collect_app_install_status_report(graph, device, config)
    document.collection_report.extend(
        [
            compliance.result,
            configuration.result,
            installed_apps.result,
            *compliance_setting_reports,
            *configuration_setting_reports,
            app_install_status.result,
        ]
    )

    windows_protection = _get_optional(
        graph,
        "windows_protection_state",
        "v1.0",
        f"/deviceManagement/managedDevices/{encoded_device_id}/windowsProtectionState",
    )
    windows_update_status = _collect_filtered_collection(
        graph,
        "windows_update_status",
        "v1.0",
        "/deviceManagement/windowsUpdateStatus",
        device,
        config,
    )
    document.collection_report.extend([windows_protection.result, windows_update_status.result])

    entra_device = _collect_entra_device(graph, device, config)
    autopilot_identity = _collect_autopilot_identity(graph, device, config)
    document.collection_report.extend([entra_device.result, autopilot_identity.result])

    endpoint_security_states, endpoint_security_reports = _collect_policy_object_device_states(
        graph,
        "endpoint_security_intent_device_states",
        "beta",
        "/deviceManagement/intents",
        "deviceStates",
        device,
        config,
        beta=True,
    )
    remediation_states, remediation_reports = _collect_script_run_states(graph, device, config)
    document.collection_report.extend([*endpoint_security_reports, *remediation_reports])

    troubleshooting = _collect_troubleshooting_events(graph, device, config)
    document.collection_report.append(troubleshooting.result)
    audit_events = _collect_audit_events(graph, device, config)
    document.collection_report.append(audit_events.result)

    endpoint_analytics: dict[str, Any] = {}
    if config.include_beta_endpoint_analytics:
        endpoint_analytics, reports = _collect_endpoint_analytics(graph, device, config)
        app_crashes = _collect_app_crashes(graph, config)
        endpoint_analytics["app_crashes"] = app_crashes.items
        reports.append(app_crashes.result)
        document.collection_report.extend(reports)
    else:
        document.warnings.append("Beta Endpoint Analytics collection was disabled.")

    for result in document.collection_report:
        if result.warning:
            warning = f"{result.name}: {result.warning}"
            if warning not in document.warnings:
                document.warnings.append(warning)

    inventory = _inventory_summary(device, config.include_pii)
    document.signals = {
        "inventory": inventory,
        "device_health_detail": device_health_detail.items[0] if device_health_detail.items else {},
        "compliance": compliance.items,
        "compliance_setting_states": compliance_setting_states,
        "configuration": configuration.items,
        "configuration_setting_states": configuration_setting_states,
        "installed_apps": installed_apps.items,
        "app_install_status": app_install_status.items,
        "health_attestation": device.get("deviceHealthAttestationState") or {},
        "security": {
            "windows_protection_state": windows_protection.items[0] if windows_protection.items else {},
            "endpoint_security_intent_device_states": endpoint_security_states,
        },
        "updates": {"windows_update_status": windows_update_status.items},
        "identity": {
            "entra_device": entra_device.items[0] if entra_device.items else {},
            "autopilot_identity": autopilot_identity.items,
        },
        "management": {
            "device_action_results": device.get("deviceActionResults") or [],
            "remediation_script_states": remediation_states,
        },
        "events": {
            "recent_restart_shutdown_events": _restart_shutdown_events(device),
            "device_timeline_events": _device_timeline_events(device, troubleshooting.items, audit_events.items, config),
        },
        "troubleshooting_events": troubleshooting.items,
        "endpoint_analytics": endpoint_analytics,
    }
    document.findings = evaluate(document.signals, config)
    document.completed_at = utc_now_iso()
    return document


def _collect_device_health_detail(graph: GraphCollectorClient, device_id: str) -> Collection:
    encoded_device_id = _path_segment(device_id)
    select = ",".join(
        [
            "id",
            "deviceName",
            "isEncrypted",
            "totalStorageSpaceInBytes",
            "freeStorageSpaceInBytes",
            "physicalMemoryInBytes",
            "processorArchitecture",
            "complianceGracePeriodExpirationDateTime",
            "managementCertificateExpirationDate",
            "deviceHealthAttestationState",
            "windowsActiveMalwareCount",
            "windowsRemediatedMalwareCount",
            "usersLoggedOn",
        ]
    )
    return _get_optional(
        graph,
        "device_health_detail",
        "beta",
        f"/deviceManagement/managedDevices/{encoded_device_id}",
        params={"$select": select},
        beta=True,
    )


def _get_optional(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    beta: bool = False,
) -> Collection:
    try:
        item = graph.get(api_version, path, params=params)
    except GraphError as exc:
        return Collection(
            [],
            EndpointResult(name, "GET", exc.url or path, api_version, "failed", exc.status_code, warning=str(exc), beta=beta),
        )
    return Collection([item], EndpointResult(name, "GET", path, api_version, "ok", 200, 1, beta=beta))


def _get_all_optional(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    max_pages: int | None = None,
    beta: bool = False,
) -> Collection:
    try:
        items, followed = graph.get_all(api_version, path, params=params, max_pages=max_pages)
    except GraphError as exc:
        return Collection(
            [],
            EndpointResult(name, "GET", exc.url or path, api_version, "failed", exc.status_code, warning=str(exc), beta=beta),
        )
    return Collection(items, EndpointResult(name, "GET", path, api_version, "ok", 200, len(items), beta=beta, next_link_followed=followed))


def _post_optional(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    path: str,
    *,
    payload: dict[str, Any],
    beta: bool = False,
) -> Collection:
    try:
        response = graph.post(api_version, path, payload=payload)
    except GraphError as exc:
        return Collection(
            [],
            EndpointResult(name, "POST", exc.url or path, api_version, "failed", exc.status_code, warning=str(exc), beta=beta),
        )
    items = _report_items(response)
    return Collection(items, EndpointResult(name, "POST", path, api_version, "ok", 200, len(items), beta=beta))


def _get_first_page_optional(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    beta: bool = False,
) -> Collection:
    try:
        response = graph.get(api_version, path, params=params)
    except GraphError as exc:
        return Collection(
            [],
            EndpointResult(name, "GET", exc.url or path, api_version, "failed", exc.status_code, warning=str(exc), beta=beta),
        )
    items = response.get("value") if isinstance(response.get("value"), list) else []
    return Collection(items, EndpointResult(name, "GET", path, api_version, "ok", 200, len(items), beta=beta, next_link_followed=False))


def _collect_installed_apps(graph: GraphCollectorClient, device_id: str, config: DiagnosticConfig) -> Collection:
    return _get_first_page_optional(
        graph,
        "installed_apps",
        "beta",
        f"/deviceManagement/managedDevices/{_path_segment(device_id)}/detectedApps",
        params={"$top": str(config.max_installed_apps)},
        beta=True,
    )


def _collect_app_crashes(graph: GraphCollectorClient, config: DiagnosticConfig) -> Collection:
    app_level = _get_first_page_optional(
        graph,
        "app_crashes",
        "beta",
        "/deviceManagement/userExperienceAnalyticsAppHealthApplicationPerformance",
        params={"$top": str(config.max_report_rows)},
        beta=True,
    )
    if app_level.result.status != "ok":
        return app_level
    crash_records = [_app_crash_summary(item) for item in app_level.items if _has_app_crash_signal(item)]
    crash_records = [item for item in crash_records if item]
    app_level.items = crash_records
    app_level.result.record_count = len(crash_records)
    return app_level


def _collect_nested_setting_states(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    base_path: str,
    parent_states: list[dict[str, Any]],
    config: DiagnosticConfig,
) -> tuple[list[dict[str, Any]], list[EndpointResult]]:
    all_items: list[dict[str, Any]] = []
    reports: list[EndpointResult] = []
    for parent in parent_states[: config.max_nested_state_queries]:
        parent_id = parent.get("id")
        if not parent_id:
            continue
        collection = _get_all_optional(
            graph,
            name,
            api_version,
            f"{base_path}/{_path_segment(parent_id)}/settingStates",
            max_pages=config.max_optional_pages,
        )
        for item in collection.items:
            item.setdefault("parentStateId", parent_id)
            item.setdefault("parentDisplayName", parent.get("displayName") or parent.get("policyDisplayName"))
        all_items.extend(collection.items)
        reports.append(collection.result)
    if not reports:
        reports.append(
            EndpointResult(
                name,
                "GET",
                f"{base_path}/{{stateId}}/settingStates",
                api_version,
                "skipped",
                warning="No parent state ids were available for setting-level collection.",
            )
        )
    return all_items, reports


def _collect_app_install_status_report(
    graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig
) -> Collection:
    device_name = device.get("deviceName")
    if not device_name:
        return Collection(
            [],
            EndpointResult(
                "device_install_status_report",
                "POST",
                "/deviceManagement/reports/getDeviceInstallStatusReport",
                "v1.0",
                "skipped",
                warning="No deviceName available for app install status report filter.",
            ),
        )
    payload = {
        "select": [
            "DeviceName",
            "UserPrincipalName",
            "Platform",
            "AppName",
            "AppVersion",
            "InstallState",
            "InstallStateDetail",
            "ErrorCode",
            "LastModifiedDateTime",
        ],
        "filter": f"(DeviceName eq '{_odata_string(device_name)}')",
        "skip": 0,
        "top": config.max_report_rows,
    }
    return _post_optional(
        graph,
        "device_install_status_report",
        "v1.0",
        "/deviceManagement/reports/getDeviceInstallStatusReport",
        payload=payload,
    )


def _collect_filtered_collection(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    path: str,
    device: dict[str, Any],
    config: DiagnosticConfig,
    *,
    beta: bool = False,
) -> Collection:
    filters = _device_filters(device)
    errors: list[str] = []
    empty_success: Collection | None = None
    for filter_value in filters:
        collection = _get_all_optional(
            graph,
            name,
            api_version,
            path,
            params={"$filter": filter_value},
            max_pages=config.max_optional_pages,
            beta=beta,
        )
        if collection.result.status == "ok":
            if collection.items:
                return collection
            empty_success = empty_success or collection
            continue
        errors.append(collection.result.warning or "unknown error")
    if empty_success is not None:
        return empty_success
    return Collection(
        [],
        EndpointResult(
            name,
            "GET",
            path,
            api_version,
            "failed" if errors else "skipped",
            warning="; ".join(errors) if errors else "No device identifiers available for filtered collection.",
            beta=beta,
        ),
    )


def _collect_entra_device(graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig) -> Collection:
    azure_id = _azure_ad_device_id(device)
    if not azure_id:
        return Collection(
            [],
            EndpointResult(
                "entra_device",
                "GET",
                "/devices",
                "v1.0",
                "skipped",
                warning="No Entra device id available for Entra device lookup.",
            ),
        )
    return _get_all_optional(
        graph,
        "entra_device",
        "v1.0",
        "/devices",
        params={
            "$filter": f"deviceId eq '{_odata_string(azure_id)}'",
            "$select": "id,deviceId,displayName,accountEnabled,trustType,approximateLastSignInDateTime,operatingSystem,operatingSystemVersion,isManaged,isCompliant",
        },
        max_pages=config.max_optional_pages,
    )


def _collect_autopilot_identity(
    graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig
) -> Collection:
    filters: list[str] = []
    azure_id = _azure_ad_device_id(device)
    serial = device.get("serialNumber")
    if azure_id:
        filters.append(f"azureActiveDirectoryDeviceId eq '{_odata_string(azure_id)}'")
    if serial:
        filters.append(f"serialNumber eq '{_odata_string(str(serial))}'")
    errors: list[str] = []
    empty_success: Collection | None = None
    for filter_value in filters:
        collection = _get_all_optional(
            graph,
            "windows_autopilot_device_identity",
            "v1.0",
            "/deviceManagement/windowsAutopilotDeviceIdentities",
            params={"$filter": filter_value},
            max_pages=config.max_optional_pages,
        )
        if collection.result.status == "ok":
            if collection.items:
                return collection
            empty_success = empty_success or collection
            continue
        errors.append(collection.result.warning or "unknown error")
    if empty_success is not None:
        return empty_success
    return Collection(
        [],
        EndpointResult(
            "windows_autopilot_device_identity",
            "GET",
            "/deviceManagement/windowsAutopilotDeviceIdentities",
            "v1.0",
            "failed" if errors else "skipped",
            warning="; ".join(errors) if errors else "No Entra device id or serial number available for Autopilot lookup.",
        ),
    )


def _collect_policy_object_device_states(
    graph: GraphCollectorClient,
    name: str,
    api_version: str,
    objects_path: str,
    states_navigation: str,
    device: dict[str, Any],
    config: DiagnosticConfig,
    *,
    beta: bool = False,
) -> tuple[list[dict[str, Any]], list[EndpointResult]]:
    objects = _get_all_optional(
        graph,
        f"{name}_objects",
        api_version,
        objects_path,
        max_pages=config.max_optional_pages,
        beta=beta,
    )
    all_items: list[dict[str, Any]] = []
    reports: list[EndpointResult] = [objects.result]
    for policy_object in objects.items[: config.max_policy_objects]:
        object_id = policy_object.get("id")
        if not object_id:
            continue
        state_collection = _collect_filtered_collection(
            graph,
            name,
            api_version,
            f"{objects_path}/{_path_segment(object_id)}/{states_navigation}",
            device,
            config,
            beta=beta,
        )
        for item in state_collection.items:
            item.setdefault("policyObjectId", object_id)
            item.setdefault("policyObjectDisplayName", policy_object.get("displayName") or policy_object.get("name"))
        all_items.extend(state_collection.items)
        reports.append(state_collection.result)
        if (
            state_collection.result.status == "failed"
            and state_collection.result.warning
            and "Invalid filter clause" in state_collection.result.warning
            and "Could not find a property named" in state_collection.result.warning
        ):
            state_collection.result.warning = (
                "Device-state filtering is not supported by this Graph resource shape; "
                "skipping remaining policy objects to avoid noisy tenant-wide calls."
            )
            break
    return all_items, reports


def _collect_script_run_states(
    graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig
) -> tuple[list[dict[str, Any]], list[EndpointResult]]:
    all_items: list[dict[str, Any]] = []
    reports: list[EndpointResult] = []
    for collection_name, objects_path, states_navigation in [
        ("device_health_script_run_states", "/deviceManagement/deviceHealthScripts", "deviceRunStates"),
        ("device_management_script_run_states", "/deviceManagement/deviceManagementScripts", "deviceRunStates"),
    ]:
        states, state_reports = _collect_policy_object_device_states(
            graph,
            collection_name,
            "beta",
            objects_path,
            states_navigation,
            device,
            config,
            beta=True,
        )
        all_items.extend(states)
        reports.extend(state_reports)
    return all_items, reports


def _collect_audit_events(graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig) -> Collection:
    filters = []
    device_id = device.get("id")
    device_name = device.get("deviceName")
    if device_id:
        filters.append(f"resources/any(r: r/resourceId eq '{_odata_string(str(device_id))}')")
    if device_name:
        filters.append(f"resources/any(r: r/displayName eq '{_odata_string(str(device_name))}')")
    errors: list[str] = []
    empty_success: Collection | None = None
    for filter_value in filters:
        collection = _get_all_optional(
            graph,
            "device_audit_timeline_events",
            "beta",
            "/deviceManagement/auditEvents",
            params={"$filter": filter_value, "$top": str(config.max_timeline_events)},
            max_pages=1,
            beta=True,
        )
        if collection.result.status == "ok":
            if collection.items:
                return collection
            empty_success = empty_success or collection
            continue
        errors.append(collection.result.warning or "unknown error")
    if empty_success is not None:
        return empty_success
    return Collection(
        [],
        EndpointResult(
            "device_audit_timeline_events",
            "GET",
            "/deviceManagement/auditEvents",
            "beta",
            "failed" if errors else "skipped",
            warning="; ".join(errors) if errors else "No device identifiers available for audit event lookup.",
            beta=True,
        ),
    )


def _collect_troubleshooting_events(
    graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig
) -> Collection:
    user_id = device.get("userId")
    if not user_id:
        return Collection(
            [],
            EndpointResult(
                "device_management_troubleshooting_events",
                "GET",
                "/users/{userId}/deviceManagementTroubleshootingEvents",
                "v1.0",
                "skipped",
                warning="Device has no userId/primary user; user-scoped troubleshooting events were skipped.",
            ),
        )
    collection = _get_all_optional(
        graph,
        "device_management_troubleshooting_events",
        "v1.0",
        f"/users/{_path_segment(user_id)}/deviceManagementTroubleshootingEvents",
        max_pages=config.max_optional_pages,
    )
    identifiers = [device.get("id"), _azure_ad_device_id(device), device.get("deviceName")]
    collection.items = [item for item in collection.items if _contains_identifier(item, identifiers)]
    collection.result.record_count = len(collection.items)
    return collection


def _collect_endpoint_analytics(
    graph: GraphCollectorClient, device: dict[str, Any], config: DiagnosticConfig
) -> tuple[dict[str, Any], list[EndpointResult]]:
    definitions = {
        "device_performance": (
            "/deviceManagement/userExperienceAnalyticsDevicePerformance",
            f"id eq '{_odata_string(str(device.get('id')))}'",
        ),
        "app_health_device_performance": (
            "/deviceManagement/userExperienceAnalyticsAppHealthDevicePerformance",
            f"deviceId eq '{_odata_string(str(device.get('id')))}'",
        ),
        "resource_performance": (
            "/deviceManagement/userExperienceAnalyticsResourcePerformance",
            f"deviceId eq '{_odata_string(str(device.get('id')))}'",
        ),
    }
    output: dict[str, Any] = {}
    reports: list[EndpointResult] = []
    for name, (path, filter_value) in definitions.items():
        collection = _get_all_optional(
            graph,
            name,
            "beta",
            path,
            params={"$filter": filter_value},
            max_pages=1,
            beta=True,
        )
        output[name] = collection.items
        reports.append(collection.result)
    return output, reports


def _collect_beta_with_filters(
    graph: GraphCollectorClient,
    name: str,
    path: str,
    azure_ad_device_id: str,
    device_name: str | None,
    config: DiagnosticConfig,
) -> Collection:
    filters: list[str] = []
    if azure_ad_device_id:
        filters.extend(
            [
                f"azureADDeviceId eq '{_odata_string(azure_ad_device_id)}'",
                f"azureAdDeviceId eq '{_odata_string(azure_ad_device_id)}'",
                f"deviceId eq '{_odata_string(azure_ad_device_id)}'",
            ]
        )
    if device_name:
        filters.extend(
            [
                f"deviceName eq '{_odata_string(device_name)}'",
                f"managedDeviceName eq '{_odata_string(device_name)}'",
            ]
        )
    errors: list[str] = []
    empty_success: Collection | None = None
    for filter_value in filters:
        collection = _get_all_optional(
            graph,
            name,
            "beta",
            path,
            params={"$filter": filter_value},
            max_pages=config.max_optional_pages,
            beta=True,
        )
        if collection.result.status == "ok":
            if collection.items:
                return collection
            empty_success = empty_success or collection
            continue
        errors.append(collection.result.warning or "unknown error")
    if empty_success is not None:
        return empty_success
    return Collection(
        [],
        EndpointResult(
            name,
            "GET",
            path,
            "beta",
            "failed" if errors else "skipped",
            warning="; ".join(errors) if errors else "No Entra device id or deviceName available for beta Endpoint Analytics lookup.",
            beta=True,
        ),
    )


def _device_filters(device: dict[str, Any]) -> list[str]:
    filters: list[str] = []
    managed_id = device.get("id")
    azure_id = _azure_ad_device_id(device)
    name = device.get("deviceName")
    if managed_id:
        filters.extend(
            [
                f"deviceId eq '{_odata_string(str(managed_id))}'",
                f"managedDeviceId eq '{_odata_string(str(managed_id))}'",
            ]
        )
    if azure_id:
        filters.extend(
            [
                f"azureADDeviceId eq '{_odata_string(azure_id)}'",
                f"azureAdDeviceId eq '{_odata_string(azure_id)}'",
                f"deviceId eq '{_odata_string(azure_id)}'",
            ]
        )
    if name:
        filters.extend(
            [
                f"deviceName eq '{_odata_string(str(name))}'",
                f"managedDeviceName eq '{_odata_string(str(name))}'",
            ]
        )
    return filters


def _path_segment(value: object) -> str:
    return quote(str(value), safe="")


def _report_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(response.get("value"), list):
        return response["value"]
    if isinstance(response.get("values"), list):
        schema = response.get("schema") or []
        columns = [item.get("column") or item.get("name") for item in schema if isinstance(item, dict)]
        items: list[dict[str, Any]] = []
        for row in response["values"]:
            if isinstance(row, dict):
                items.append(row)
            elif isinstance(row, list) and columns:
                items.append({columns[index] if index < len(columns) else str(index): value for index, value in enumerate(row)})
            else:
                items.append({"value": row})
        return items
    if isinstance(response.get("Value"), list):
        return response["Value"]
    return [response] if response else []


def _has_app_crash_signal(item: dict[str, Any]) -> bool:
    return any(_as_number(item.get(field)) and _as_number(item.get(field)) > 0 for field in ["appCrashCount", "appHangCount", "crashCount", "hangCount"])


def _app_crash_summary(item: dict[str, Any]) -> dict[str, Any]:
    fields = [
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
    ]
    return {field: item.get(field) for field in fields if item.get(field) not in (None, "", [], {})}


def _restart_shutdown_events(device: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for action in device.get("deviceActionResults") or []:
        action_name = str(action.get("actionName") or "")
        if action_name.lower() not in {"rebootnow", "shutdown", "shutdownnow"}:
            continue
        events.append(
            {
                "source": "intune_device_action",
                "eventType": "restart" if action_name.lower() == "rebootnow" else "shutdown",
                "actionName": action_name,
                "state": action.get("actionState"),
                "startDateTime": action.get("startDateTime"),
                "lastUpdatedDateTime": action.get("lastUpdatedDateTime"),
            }
        )
    return _sort_events(events)


def _device_timeline_events(
    device: dict[str, Any],
    troubleshooting_events: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    config: DiagnosticConfig,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for action in device.get("deviceActionResults") or []:
        events.append(
            {
                "source": "intune_device_action",
                "eventType": "device_action",
                "actionName": action.get("actionName"),
                "state": action.get("actionState"),
                "startDateTime": action.get("startDateTime"),
                "lastUpdatedDateTime": action.get("lastUpdatedDateTime"),
            }
        )
    for event in troubleshooting_events:
        events.append(
            {
                "source": "intune_troubleshooting_event",
                "eventType": event.get("eventType") or event.get("type") or "troubleshooting",
                "status": event.get("status"),
                "eventDateTime": event.get("eventDateTime") or event.get("createdDateTime") or event.get("lastUpdatedDateTime"),
                "message": event.get("message") or event.get("description") or event.get("displayName"),
                "errorCode": event.get("errorCode"),
            }
        )
    for event in audit_events:
        actor = event.get("actor") or {}
        events.append(
            {
                "source": "intune_audit_event",
                "eventType": "audit",
                "activity": event.get("activity"),
                "activityType": event.get("activityType"),
                "activityResult": event.get("activityResult"),
                "activityDateTime": event.get("activityDateTime"),
                "category": event.get("category"),
                "actor": actor.get("applicationDisplayName") or actor.get("userPrincipalName") or actor.get("servicePrincipalName"),
            }
        )
    return _sort_events(events)[: config.max_timeline_events]


def _sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def event_time(event: dict[str, Any]) -> str:
        return str(
            event.get("activityDateTime")
            or event.get("eventDateTime")
            or event.get("lastUpdatedDateTime")
            or event.get("startDateTime")
            or ""
        )

    return sorted([event for event in events if any(value not in (None, "", [], {}) for value in event.values())], key=event_time, reverse=True)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _inventory_summary(device: dict[str, Any], include_pii: bool) -> dict[str, Any]:
    hardware = dict(device.get("hardwareInformation") or {})
    for pii_key in ["serialNumber", "imei", "meid", "phoneNumber", "subscriberCarrier", "wifiMac"]:
        if pii_key in hardware:
            hardware[pii_key] = redact(hardware.get(pii_key), include_pii)
    return {
        "id": device.get("id"),
        "deviceName": device.get("deviceName"),
        "azureADDeviceId": _azure_ad_device_id(device) or None,
        "userId": redact(device.get("userId"), include_pii),
        "userPrincipalName": redact(device.get("userPrincipalName"), include_pii),
        "serialNumber": redact(device.get("serialNumber"), include_pii),
        "operatingSystem": device.get("operatingSystem"),
        "osVersion": device.get("osVersion"),
        "manufacturer": device.get("manufacturer"),
        "model": device.get("model"),
        "complianceState": device.get("complianceState"),
        "managementState": device.get("managementState"),
        "lastSyncDateTime": device.get("lastSyncDateTime"),
        "enrolledDateTime": device.get("enrolledDateTime"),
        "hardwareInformation": hardware,
    }


def _contains_identifier(value: Any, identifiers: list[Any]) -> bool:
    text = str(value).casefold()
    return any(str(identifier).casefold() in text for identifier in identifiers if identifier)


def _odata_string(value: str) -> str:
    return value.replace("'", "''")
