# Collector module evolution backlog

This page proposes future local collector modules for Agent-Azure-FarSight. The intent is to complement Intune data, not duplicate it. Intune already provides strong inventory, compliance, configuration profile, app deployment, update, and device health signals. These modules should start from those signals and then collect deeper, time-bounded, application-aware evidence from the Windows endpoint.

## Selection principles

- Prefer **hypothesis-driven diagnostics** over broad inventory.
- Collect **bounded, redacted, point-in-time evidence** that helps an SRE agent explain an incident.
- Avoid remote shell patterns and arbitrary command execution.
- Keep each module **allowlisted, parameterized, schema-validated, timeout-bounded, and artifact-size-bounded**.
- Return structured summaries first; emit artifacts only when the detail is useful for analysis.

## Proposed modules

| # | Module | Diagnostic question | Why Intune is not enough | Evidence returned |
|---|---|---|---|---|
| 1 | `Get-AppLogBundle` | What application log evidence exists under an approved local log folder for a specific machine/app/time window? | Intune can collect generic diagnostics, but it does not know each custom app's log folder layout, naming patterns, rotation scheme, or incident-specific filters. | ZIP artifact containing bounded matching log files plus a manifest with included/skipped files, hashes, sizes, timestamps, and redaction summary. |
| 2 | `Get-AppDependencyGraphSnapshot` | Which local services, processes, files, certs, registry keys, ports, and scheduled tasks appear tied to a target app? | Intune can show installed apps and managed assignments, but not runtime dependency relationships. | Graph summary with nodes/edges, missing dependencies, suspicious drift, optional JSON artifact. |
| 3 | `Get-ProcessThreadWaitSnapshot` | Is an app hung because of blocked threads, high wait counts, or deadlock-like behavior? | Intune does not inspect live thread/wait state. | Process/thread counts, CPU deltas, wait indicators, top stacks when safe/available, warnings. |
| 4 | `Get-AppHandlePressureSnapshot` | Is the target process leaking handles or exhausting GDI/user objects? | Intune inventory does not expose resource pressure within processes. | Handle counts by type where available, GDI/user object counts, trend compared with previous local run. |
| 5 | `Get-NamedPipeEndpointSnapshot` | Are local IPC named pipes present and owned by expected processes? | Intune does not map local IPC surfaces used by app agents/services. | Pipe names matched to approved patterns, owner process, missing/extra pipe warnings. |
| 6 | `Get-LocalPortOwnershipSnapshot` | Which process owns the app's expected local listening ports, and are unexpected ports exposed? | Intune does not provide live socket ownership or bind conflicts. | TCP/UDP listeners, owning process/service, bind address, approved/unapproved classification. |
| 7 | `Test-AppDnsResolutionPath` | Does the endpoint resolve app dependencies through expected DNS servers and suffixes? | Intune networking state is generic and does not trace app-specific DNS paths. | Resolver list, search suffixes, per-name answers, latency, split-DNS mismatch warnings. |
| 8 | `Test-AppProxyAndPacResolution` | Is proxy/PAC configuration causing app connectivity failures? | Intune can deploy proxy settings but cannot validate live PAC evaluation for specific URLs. | Effective WinHTTP/WinINET proxy, PAC URL reachability, target URL proxy decision, failures. |
| 9 | `Test-AppTlsChainAndRevocation` | Are TLS failures caused by chain, EKU, expiration, trust store, or revocation checks? | Intune may deploy certificates but does not diagnose live target TLS chain behavior. | Certificate chain summary, trust result, revocation status, EKU/SAN checks, thumbprints. |
| 10 | `Get-AppCredentialProviderSnapshot` | Are Windows Credential Manager or enterprise auth providers in a state that could break app sign-in? | Intune reports compliance/configuration, not per-app auth provider state. | Provider availability, relevant credential entries metadata only, timestamps, redacted identifiers. |
| 11 | `Get-TokenBrokerHealthSnapshot` | Are WAM/AAD Broker Plugin components failing for app authentication? | Intune can show registration/compliance but not local token broker operational evidence. | Broker package status, selected event slices, plugin process state, cache metadata without tokens. |
| 12 | `Get-UserProfileStateSnapshot` | Is the app failing because the user profile, shell folders, or redirected folders are unhealthy? | Intune does not deeply inspect profile path consistency for app runtime. | Profile path state, known folders, disk availability, stale temp/cache paths, access checks. |
| 13 | `Get-AppFileLockSnapshot` | Which process is locking an app config/log/database file? | Intune does not identify file lock contention. | Approved target file paths, locking process metadata when available, access-denied patterns. |
| 14 | `Get-AppConfigDriftSnapshot` | Did app-local config files or registry keys drift from approved profiles? | Intune may deploy desired settings but does not diff arbitrary app-local config safely. | Hashes, selected key/value comparisons, redacted diffs, last-write timestamps. |
| 15 | `Get-LocalCertificateStoreDiff` | Are required app certificates present in the right stores and chains? | Intune certificate deployment state may not prove final local store placement and usability. | Store inventory for approved subjects/thumbprints, private-key presence flag, expiry, chain status. |
| 16 | `Get-WindowsFilteringPlatformTraceSlice` | Is Windows Firewall/WFP blocking the app or dependency endpoint? | Intune firewall policy status does not explain live block events for a specific flow. | Time-bounded firewall/security event slice, process/path correlation, rule/profile hints. |
| 17 | `Get-AppCrashTriageBundle` | What changed around a crash: WER, event log, module versions, dumps metadata? | Intune can show app install state but not crash-local triage context. | WER reports, faulting module, app version, exception code, optional bounded metadata artifact. |
| 18 | `Get-InstallerTransactionTrace` | Did a recent app install/update fail due to MSI, winget, Store, or custom installer errors? | Intune reports deployment status but often lacks local transaction details. | MSI/AppX/winget logs slice, installer exit codes, reboot pending flags, recent install timeline. |
| 19 | `Get-RebootDebtSnapshot` | Is the endpoint in a pending-reboot state that explains app/update failures? | Intune may know update status but not all local reboot debt sources. | CBS, Windows Update, pending file rename, component servicing, SCCM/third-party indicators. |
| 20 | `Get-AppDiskHotspotSnapshot` | Is the app slowed by local disk pressure, hot directories, or pathological file counts? | Intune reports disk capacity but not app-specific IO/file layout problems. | Approved directory file counts, largest/newest files, sparse/temp/cache hotspots, free-space context. |
| 21 | `Get-TimeAndTrustSkewSnapshot` | Are time drift, domain trust, or secure channel issues breaking authentication/connectivity? | Intune compliance does not diagnose local secure-channel/time-skew causes in detail. | Time source, skew estimate, domain secure channel status, Kerberos-relevant event slices. |

## Suggested implementation priority

1. **Authentication/connectivity depth**: `Test-AppDnsResolutionPath`, `Test-AppProxyAndPacResolution`, `Test-AppTlsChainAndRevocation`, `Get-TokenBrokerHealthSnapshot`.
2. **Application log collection**: `Get-AppLogBundle` for incident-specific custom app logs when Intune diagnostics are too generic.
3. **Runtime health**: `Get-ProcessThreadWaitSnapshot`, `Get-AppHandlePressureSnapshot`, `Get-LocalPortOwnershipSnapshot`.
4. **Crash and install triage**: `Get-AppCrashTriageBundle`, `Get-InstallerTransactionTrace`, `Get-RebootDebtSnapshot`.
5. **Configuration and dependency drift**: `Get-AppDependencyGraphSnapshot`, `Get-AppConfigDriftSnapshot`, `Get-LocalCertificateStoreDiff`.

## `Get-AppLogBundle` module shape

`Get-AppLogBundle` is a high-value first candidate because it gives the SRE agent targeted application logs without giving it arbitrary file-system access.

Recommended parameters:

| Parameter | Purpose | Guardrail |
|---|---|---|
| `machine` | Target machine/device identifier selected by the SRE agent. | Must match the FarSight device/job target; not used for remote access by the module. |
| `appId` | Approved application profile name. | Resolves allowed roots, file patterns, redaction profile, and max limits from policy/manifest. |
| `logPathFolder` | Local folder where the custom application stores logs. | Must be under an approved root for `appId`; reject free-form system paths. |
| `includeFilters` | File name globs or regex-like filters for files to include, for example `*.log`, `app-*.jsonl`. | Bounded list; no path traversal; evaluated against file name or relative path only. |
| `excludeFilters` | Filters for files to skip, for example `*.dmp`, `*.bak`, `*secret*`. | Enforced after include filters; default excludes sensitive or huge file types. |
| `startTimeUtc` / `endTimeUtc` | Optional last-write or embedded timestamp window for incident-focused collection. | Maximum lookback and window size enforced by schema. |
| `maxFiles` | Maximum files to include. | Hard cap, for example 50. |
| `maxBytes` | Maximum total ZIP size before compression. | Hard cap, for example 50 MB or lower by risk tier. |
| `tailLines` | Optional tail-only mode for text logs. | Prevents full-file collection when only recent entries are needed. |
| `redactionProfile` | Redaction rule set for secrets, tokens, usernames, connection strings, and PII. | Defaults to the app profile; cannot be disabled in production. |

Expected output:

- Summary with matched file count, included file count, skipped file count, total bytes, earliest/latest timestamps, and redaction count.
- ZIP artifact containing the selected logs and `manifest.json`.
- `manifest.json` listing every included and skipped file with relative path, size, last-write time, SHA-256, and skip reason.
- Findings for no-match, access denied, excessive size, excluded sensitive files, stale logs, or timestamp gaps.

## Guardrail notes

- Modules that inspect user profile, credential, certificate, or auth broker data must return metadata only and redact account names where possible.
- Modules that inspect files must use approved profiles instead of free-form paths.
- Modules that can produce large artifacts should summarize first and cap artifacts by size and time window.
- Network modules must use approved hostnames, URLs, ports, and expected certificate thumbprints from the job schema or app profile.
