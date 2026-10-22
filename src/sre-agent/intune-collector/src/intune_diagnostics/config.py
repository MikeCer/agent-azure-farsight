from __future__ import annotations

from dataclasses import dataclass


EVIDENCE_SECTIONS = (
    "device", "device_health", "performance", "installed_applications", "app_crashes",
    "recent_restart_shutdown_events", "device_timeline_events", "policy_and_configuration_issues",
    "app_installation_issues", "security_issues", "windows_update_issues", "management_failures",
    "identity_issues", "troubleshooting_errors", "memory", "cpu", "storage",
)

HARDWARE_FIELDS = {
    "memory": ("physicalMemoryInBytes",),
    "cpu": ("processorArchitecture",),
    "storage": ("totalStorageSpaceInBytes", "freeStorageSpaceInBytes"),
}


def parse_sections(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ValueError("sections must be a comma-separated string.")
    sections = tuple(dict.fromkeys(part.strip() for part in value.split(",")))
    if not sections or any(section not in ("full", *EVIDENCE_SECTIONS) for section in sections):
        raise ValueError(f"sections must contain full or names from: {', '.join(EVIDENCE_SECTIONS)}.")
    if "full" in sections and len(sections) != 1:
        raise ValueError("sections=full cannot be combined with individual sections.")
    return sections


@dataclass(frozen=True)
class DiagnosticConfig:
    stale_checkin_high_days: int = 7
    stale_checkin_medium_days: int = 3
    low_memory_gb: int = 8
    low_storage_capacity_gb: int = 128
    poor_score_threshold: int = 50
    slow_boot_seconds: int = 120
    troubleshooting_error_high_count: int = 3
    max_resolution_pages: int = 20
    max_optional_pages: int = 5
    max_installed_apps: int = 150
    max_nested_state_queries: int = 25
    max_report_rows: int = 100
    max_policy_objects: int = 25
    max_timeline_events: int = 25
    include_beta_endpoint_analytics: bool = True
    include_pii: bool = False
    graph_timeout_seconds: int = 15
    graph_max_retries: int = 2
    sections: str = "full"

    def __post_init__(self) -> None:
        parse_sections(self.sections)

    @property
    def requested_sections(self) -> tuple[str, ...]:
        return parse_sections(self.sections)

    def includes(self, *sections: str) -> bool:
        return "full" in self.requested_sections or bool(set(sections).intersection(self.requested_sections))
