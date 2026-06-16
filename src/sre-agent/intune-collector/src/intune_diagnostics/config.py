from __future__ import annotations

from dataclasses import dataclass


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
