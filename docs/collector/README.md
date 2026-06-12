# Collector

The FarSight collector is a PowerShell scheduled-task workload deployed by Intune. Current scripts are early implementation and should be tested with sample configuration before tenant rollout.

## Endpoint folder layout

- `config/` - signed collector and module configuration.
- `modules/` - allowlisted module scripts and schemas.
- `state/` - local job cache, retry metadata, and last check-in.
- `logs/` - structured operational logs with sensitive values redacted.
- `artifacts/` - bounded optional artifacts awaiting upload.

## Scheduled task model

The collector runs as a scheduled task under the approved local identity. It checks in on a configured cadence, applies backoff on failures, and never accepts free-form shell commands.

## Configuration

Configuration should include API endpoint, tenant, certificate binding, module manifest version, log level, timeout defaults, and artifact limits.

## Local state

State must be minimal, encrypted or access-controlled where practical, and safe to delete. Job state should support retries without duplicating evidence.

## Logging and troubleshooting

- Log job IDs, module IDs, duration, status, and redaction events.
- Do not log secrets, raw certificates, tokens, usernames, or arbitrary paths.
- Start troubleshooting with collector health, certificate validity, API reachability, manifest version, and module schema validation.

## Known gaps

- Add exact Windows Event Log source and log file paths after implementation stabilizes.
