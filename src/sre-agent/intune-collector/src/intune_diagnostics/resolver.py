from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import DiagnosticConfig
from .graph_client import GraphError


class GraphReader(Protocol):
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
class DeviceResolutionError(Exception):
    kind: str
    message: str
    candidates: list[dict[str, Any]] | None = None
    status_code: int | None = None
    url: str | None = None
    error_code: str | None = None
    identity_context: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class DeviceDisambiguation:
    managed_device_id: str | None = None
    azure_ad_device_id: str | None = None
    serial_number: str | None = None


DEVICE_SELECT = ",".join(
    [
        "id",
        "deviceName",
        "azureADDeviceId",
        "azureAdDeviceId",
        "serialNumber",
        "userId",
        "userPrincipalName",
        "lastSyncDateTime",
        "enrolledDateTime",
        "operatingSystem",
        "osVersion",
        "manufacturer",
        "model",
        "complianceState",
    ]
)


def resolve_device_by_name(
    graph: GraphReader,
    device_name: str,
    config: DiagnosticConfig,
    *,
    disambiguation: DeviceDisambiguation | None = None,
) -> dict[str, Any]:
    name = device_name.strip()
    if not name:
        raise DeviceResolutionError("invalid_input", "deviceName cannot be empty")

    try:
        matches = _server_filter_matches(graph, name, config)
        if matches is None:
            matches = _client_side_matches(graph, name, config)
    except GraphError as exc:
        raise _resolution_graph_error(exc) from exc

    if disambiguation:
        matches = _apply_disambiguation(matches, disambiguation)

    if not matches:
        raise DeviceResolutionError("not_found", f"No Intune managed device found with deviceName '{name}'")
    if len(matches) > 1:
        raise DeviceResolutionError(
            "ambiguous",
            f"Multiple Intune managed devices found with deviceName '{name}'. Provide a more specific identifier.",
            candidates=[_candidate_summary(item) for item in matches],
        )
    return matches[0]


def _server_filter_matches(graph: GraphReader, device_name: str, config: DiagnosticConfig) -> list[dict[str, Any]] | None:
    params = {"$select": DEVICE_SELECT, "$filter": f"deviceName eq '{_odata_string(device_name)}'"}
    try:
        items, _ = graph.get_all(
            "v1.0", "/deviceManagement/managedDevices", params=params, max_pages=config.max_resolution_pages
        )
    except GraphError as exc:
        if exc.status_code in {400, 501}:
            return None
        raise
    return [item for item in items if item.get("deviceName") == device_name]


def _resolution_graph_error(exc: GraphError) -> DeviceResolutionError:
    if exc.status_code in {401, 403}:
        kind = "authorization_error"
        message = (
            f"Intune managed-device lookup failed with HTTP {exc.status_code}. "
            "Verify the calling identity is in the correct tenant and has Microsoft Graph application permission "
            "DeviceManagementManagedDevices.Read.All with admin consent."
        )
    elif exc.status_code == 404:
        kind = "endpoint_not_found"
        message = "Intune managed-device lookup endpoint was not found. Verify Microsoft Intune is available in the target tenant."
    else:
        kind = "collection_error"
        message = f"Intune managed-device lookup failed: {exc}"
    return DeviceResolutionError(
        kind,
        message,
        status_code=exc.status_code,
        url=exc.url,
        error_code=exc.error_code,
        identity_context=exc.identity_context,
    )


def _client_side_matches(graph: GraphReader, device_name: str, config: DiagnosticConfig) -> list[dict[str, Any]]:
    params = {"$select": DEVICE_SELECT}
    items, _ = graph.get_all(
        "v1.0", "/deviceManagement/managedDevices", params=params, max_pages=config.max_resolution_pages
    )
    return [item for item in items if item.get("deviceName") == device_name]


def _apply_disambiguation(
    matches: list[dict[str, Any]], disambiguation: DeviceDisambiguation
) -> list[dict[str, Any]]:
    filtered = matches
    if disambiguation.managed_device_id:
        filtered = [item for item in filtered if item.get("id") == disambiguation.managed_device_id]
    if disambiguation.azure_ad_device_id:
        filtered = [
            item
            for item in filtered
            if _azure_ad_device_id(item).casefold() == disambiguation.azure_ad_device_id.casefold()
        ]
    if disambiguation.serial_number:
        filtered = [
            item
            for item in filtered
            if str(item.get("serialNumber", "")).casefold() == disambiguation.serial_number.casefold()
        ]
    return filtered


def _candidate_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "deviceName": item.get("deviceName"),
        "azureADDeviceId": _azure_ad_device_id(item),
        "userPrincipalName": item.get("userPrincipalName"),
        "serialNumber": item.get("serialNumber"),
        "lastSyncDateTime": item.get("lastSyncDateTime"),
        "enrolledDateTime": item.get("enrolledDateTime"),
        "operatingSystem": item.get("operatingSystem"),
        "osVersion": item.get("osVersion"),
        "manufacturer": item.get("manufacturer"),
        "model": item.get("model"),
    }


def _azure_ad_device_id(item: dict[str, Any]) -> str:
    return str(item.get("azureADDeviceId") or item.get("azureAdDeviceId") or "")


def _odata_string(value: str) -> str:
    return value.replace("'", "''")
