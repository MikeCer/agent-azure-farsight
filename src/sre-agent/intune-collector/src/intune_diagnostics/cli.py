from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DiagnosticConfig
from .tool import main as collect_intune_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect read-only Intune diagnostics for one Windows client device.")
    parser.add_argument("--device-name", required=True, help="Required Intune deviceName to diagnose.")
    parser.add_argument("--auth-mode", choices=["auto", "default", "client-secret"], default="auto")
    parser.add_argument("--tenant-id", help="Optional tenant id metadata to include in output.")
    parser.add_argument("--managed-device-id", help="Optional disambiguator when deviceName matches multiple Intune records.")
    parser.add_argument("--azure-ad-device-id", help="Optional disambiguator when deviceName matches multiple Intune records.")
    parser.add_argument("--serial-number", help="Optional disambiguator when deviceName matches multiple Intune records.")
    parser.add_argument("--output", type=Path, help="Write JSON output to this file instead of stdout.")
    parser.add_argument("--include-pii", action="store_true", help="Include user and device identifiers that may be PII.")
    parser.add_argument(
        "--no-include-beta-endpoint-analytics",
        action="store_true",
        help="Disable beta Endpoint Analytics collection.",
    )
    parser.add_argument("--max-resolution-pages", type=int, default=DiagnosticConfig.max_resolution_pages)
    parser.add_argument("--max-optional-pages", type=int, default=DiagnosticConfig.max_optional_pages)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = DiagnosticConfig(
        include_beta_endpoint_analytics=not args.no_include_beta_endpoint_analytics,
        include_pii=args.include_pii,
        max_resolution_pages=args.max_resolution_pages,
        max_optional_pages=args.max_optional_pages,
    )
    payload = collect_intune_diagnostics(
        device_name=args.device_name,
        auth_mode=args.auth_mode,
        tenant_id=args.tenant_id,
        managed_device_id=args.managed_device_id,
        azure_ad_device_id=args.azure_ad_device_id,
        serial_number=args.serial_number,
        include_pii=args.include_pii,
        include_beta_endpoint_analytics=config.include_beta_endpoint_analytics,
        max_resolution_pages=config.max_resolution_pages,
        max_optional_pages=config.max_optional_pages,
    )
    _write_output(payload, args.output)
    issue_ids = {item.get("id") for item in payload.get("issues", []) if isinstance(item, dict)}
    if "device-resolution-collection_error" in issue_ids:
        return 1
    if "device-resolution-authorization_error" in issue_ids:
        return 1
    if any(issue_id and str(issue_id).startswith("device-resolution-") for issue_id in issue_ids):
        return 2
    return 0


def _write_output(payload: dict[str, object], output: Path | None) -> None:
    import json

    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    if output:
        output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)


if __name__ == "__main__":
    raise SystemExit(main())
