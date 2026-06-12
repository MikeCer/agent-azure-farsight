# Intune Data Catalog

This catalog documents the evidence collected by the Intune Diagnostics Collector. The collector is read-only and uses Microsoft Graph/Intune data that already exists in the tenant. It does not connect to the Windows client directly.

## Common Output Mapping

| Output area | Purpose |
| --- | --- |
| `target` | Input `deviceName` and resolved Intune/Entra identifiers |
| `assessment` | Generated time, highest severity, issue count, performance status, and top concerns |
| `issues` | Deterministic rule findings with severity, confidence, compact evidence, and remediation steps |
| `diagnostic_evidence.device` | Minimal device identity, OS, model, compliance, management, enrollment, and sync context |
| `diagnostic_evidence.device_health` | Enriched Intune beta device health, encryption, storage, memory, malware, and certificate-expiration details |
| `diagnostic_evidence.performance` | Endpoint Analytics startup, resource, and app reliability metrics useful for performance diagnosis |
| `diagnostic_evidence.installed_applications` | Installed/detected applications for the device: app name, publisher, and version |
| `diagnostic_evidence.app_crashes` | Endpoint Analytics app crash summary and crashing application list when available |
| `diagnostic_evidence.recent_restart_shutdown_events` | Intune-initiated restart/shutdown actions recorded on the managed device |
| `diagnostic_evidence.device_timeline_events` | Timeline-style events from Intune device actions, troubleshooting events, and matching audit events |
| `diagnostic_evidence.policy_and_configuration_issues` | Only noncompliant/error/conflict policy or setting rows |
| `diagnostic_evidence.app_installation_issues` | Only failed app install rows when available |
| `diagnostic_evidence.security_issues` | Only risky Windows protection fields |
| `diagnostic_evidence.windows_update_issues` | Only Windows update records needing attention |
| `diagnostic_evidence.management_failures` | Only failed device actions, scripts, or remediations |
| `diagnostic_evidence.identity_issues` | Only Entra device identity states that can block management/access |

## Managed Device Resolution

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices` |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All` |
| Request | First tries `$filter=deviceName eq '{deviceName}'` with `$select` for minimal identity fields. If the tenant rejects the filter, falls back to capped paged matching with `$select`. |
| Retrieved information | `id`, `deviceName`, `azureADDeviceId`/`azureAdDeviceId`, `serialNumber`, `userId`, `userPrincipalName`, `lastSyncDateTime`, `enrolledDateTime`, `operatingSystem`, `osVersion`, `manufacturer`, `model`, `complianceState` |
| Output mapping | `target`, `signals.inventory`, ambiguity candidates when multiple records match |
| Diagnostic use | `device-resolution-not_found`, `device-resolution-ambiguous`, downstream joins |
| Caveats | `deviceName` is not unique. Server-side filtering is not supported consistently across tenants, so fallback matching is capped by `--max-resolution-pages`. |
| Sensitive data | UPN and serial number can be sensitive; redacted unless `include_pii` is set to `true`. |

## Managed Device Detail and Health Attestation

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}` |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All` |
| Request | Uses `$expand=deviceHealthAttestationState` where supported. |
| Retrieved information | Managed-device inventory fields, `hardwareInformation`, `deviceHealthAttestationState`, compliance/management/check-in fields |
| Output mapping | `signals.inventory`, `signals.health_attestation` |
| Diagnostic use | `stale-intune-checkin`, `device-noncompliant`, `health-attestation-risk`, `hardware-capacity-bottleneck`, `management-action-or-script-failures` |
| Caveats | Health attestation and hardware inventory freshness depends on device check-in and platform support. Missing optional fields are omitted from the final JSON. |
| Sensitive data | Hardware identifiers can include serial number, IMEI, phone, carrier, and MAC address; redacted where modeled unless `include_pii` is set to `true`. |

### Enriched Device Health Detail

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All` |
| Request | Uses `$select` for `isEncrypted`, storage, memory, processor architecture, compliance grace period, management certificate expiration, health attestation, malware counts, and logged-on users. |
| Retrieved information | `isEncrypted`, `totalStorageSpaceInBytes`, `freeStorageSpaceInBytes`, computed `freeStoragePercent`, `physicalMemoryInBytes`, `processorArchitecture`, `complianceGracePeriodExpirationDateTime`, `managementCertificateExpirationDate`, `windowsActiveMalwareCount`, `windowsRemediatedMalwareCount`, `usersLoggedOn` |
| Output mapping | `diagnostic_evidence.device_health` |
| Diagnostic use | Adds evidence for encryption/BitLocker failures, storage bottlenecks, memory sizing, malware state, and management certificate freshness. |
| Caveats | Beta API fields can change. This is still Intune inventory and depends on device check-in freshness. |
| Sensitive data | Logged-on user information can be sensitive and is redacted unless PII output is enabled. |

### Device Action Results

| Item | Details |
| --- | --- |
| Source | `deviceActionResults` property on `managedDevice` detail |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All` |
| Retrieved information | Device action name, action state/status, start/completion timestamps, and error-like fields where returned |
| Output mapping | `signals.management.device_action_results` |
| Diagnostic use | `management-action-or-script-failures` |
| Caveats | This is a property of the managed-device payload, not a separate endpoint. History depth depends on Intune. |
| Sensitive data | Low to medium; action history can reveal admin operations. |

### Recent Restart/Shutdown Events

| Item | Details |
| --- | --- |
| Source | `deviceActionResults` property on `managedDevice` detail |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All` |
| Retrieved information | Intune device actions with `actionName` of `rebootNow`, `shutDown`, or `shutdownNow`; action state, start time, last update time |
| Output mapping | `diagnostic_evidence.recent_restart_shutdown_events` |
| Diagnostic use | Shows recent admin-initiated restart/shutdown actions that can explain user disruption or device state changes. |
| Caveats | This is not the Windows System event log. It does not include user-initiated or OS-initiated restart/shutdown event IDs unless those actions were initiated through Intune. |
| Sensitive data | Low to medium; action history can reveal admin operations. |

### Device Timeline Events

| Item | Details |
| --- | --- |
| Sources | `deviceActionResults`, `/users/{userId}/deviceManagementTroubleshootingEvents`, and `/deviceManagement/auditEvents` filtered by device resource id/name |
| API version | `v1.0` for device action/troubleshooting sources; `beta` for Intune audit event lookup |
| Permissions | `DeviceManagementManagedDevices.Read.All`; audit lookup may require Intune audit read access through the same app permissions/RBAC |
| Retrieved information | Event source, event type, action/activity name, state/status/result, timestamp, actor when available |
| Output mapping | `diagnostic_evidence.device_timeline_events` |
| Diagnostic use | Provides a compact chronological context of Intune management activity around the device. |
| Caveats | Microsoft Graph did not expose a supported `/managedDevices/{id}/timelineEvents` endpoint in live tests. Timeline events are therefore reconstructed from Intune sources that are available through Graph and are not equivalent to OS event logs captured directly on the endpoint. |
| Sensitive data | Actor and activity information can be sensitive. |

## Device Compliance Policy States

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}/deviceCompliancePolicyStates` |
| API version | `v1.0` |
| Permissions | `DeviceManagementConfiguration.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | Managed-device navigation property; paged with `@odata.nextLink`. |
| Retrieved information | Compliance policy state records, policy names/ids where available, state/status/error fields |
| Output mapping | `signals.compliance` |
| Diagnostic use | `device-noncompliant` |
| Caveats | Returned schema can vary by policy type. Absence of rows does not always mean compliant; compare with managed-device `complianceState`. |
| Sensitive data | Usually low, but policy names can reveal security configuration. |

## Device Compliance Policy Setting States

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}/deviceCompliancePolicyStates/{stateId}/settingStates` |
| API version | `v1.0` |
| Permissions | `DeviceManagementConfiguration.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | For each compliance policy state with an `id`, queries setting-level states up to `max_nested_state_queries`; paged with `@odata.nextLink`. |
| Retrieved information | Setting name/id, setting state/status, error codes, source policy state id/display name where available |
| Output mapping | `signals.compliance_setting_states` |
| Diagnostic use | `setting-level-policy-failures`, `device-noncompliant` |
| Caveats | Some policy state types may not expose setting-level states. Missing/unsupported calls become collection warnings. |
| Sensitive data | Setting names can reveal security policy design. |

## Device Configuration States

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}/deviceConfigurationStates` |
| API version | `v1.0` |
| Permissions | `DeviceManagementConfiguration.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | Managed-device navigation property; paged with `@odata.nextLink`. |
| Retrieved information | Configuration profile state records, profile names/ids where available, state/status/error fields |
| Output mapping | `signals.configuration` |
| Diagnostic use | Supports remediation context for compliance/configuration findings. |
| Caveats | Configuration state details can lag behind assignment changes and device sync. |
| Sensitive data | Profile names can reveal internal configuration standards. |

## Device Configuration Setting States

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}/deviceConfigurationStates/{stateId}/settingStates` |
| API version | `v1.0` |
| Permissions | `DeviceManagementConfiguration.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | For each configuration state with an `id`, queries setting-level states up to `max_nested_state_queries`; paged with `@odata.nextLink`. |
| Retrieved information | Setting name/id, setting state/status, error codes, parent configuration profile context where available |
| Output mapping | `signals.configuration_setting_states` |
| Diagnostic use | `setting-level-policy-failures` |
| Caveats | This navigation may not be available for every profile family or tenant shape. Unsupported calls are warnings, not hard failures. |
| Sensitive data | Setting names can reveal internal configuration standards. |

## Device App Install Status Report

| Item | Details |
| --- | --- |
| Endpoint | `POST /deviceManagement/reports/getDeviceInstallStatusReport` |
| API version | `v1.0` |
| Permissions | `DeviceManagementApps.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | Posts a report request filtered by `DeviceName`, selecting app name/version/platform/install state/detail/error code/timestamp columns and capped by `max_report_rows`. |
| Retrieved information | App assignment/install status rows, install state, install state detail, error code, last modified time |
| Output mapping | `signals.app_install_status` |
| Diagnostic use | `app-install-failures` |
| Caveats | Intune report schemas and filter column names can vary. Unsupported filters or missing permissions are omitted unless they produce actionable issues. |
| Sensitive data | App names and user/app assignment state can be sensitive. |

## Installed Applications

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}/detectedApps` |
| API version | `beta` |
| Permissions | `DeviceManagementApps.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | Reads the first page of apps detected on the target device, capped by `max_installed_apps`. |
| Retrieved information | App display name, publisher, and version |
| Output mapping | `diagnostic_evidence.installed_applications` |
| Diagnostic use | Helps correlate user symptoms, known problematic versions, and app reliability findings. |
| Caveats | This is Intune detected-app inventory, not a live process list. It can lag behind the device and does not prove an app was running during a crash. Microsoft Graph `detectedApp` exposes `id`, `displayName`, `version`, `sizeInByte`, `deviceCount`, `publisher`, and `platform`; it does not expose a per-device application installation date. Live probes for `deviceInstalledApps` and `mobileAppIntentAndStates` also returned unsupported in this tenant. |
| Sensitive data | Installed app inventory can reveal user or business workload. |

## App Crash List

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/userExperienceAnalyticsAppHealthApplicationPerformance` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementServiceConfig.Read.All` |
| Request | Reads Endpoint Analytics app health data and keeps applications with crash/hang counts greater than zero. |
| Retrieved information | App display/name, publisher/version when returned, app health score/status, crash count, hang count, mean time to failure, active device count |
| Output mapping | `diagnostic_evidence.app_crashes.crashing_applications` |
| Diagnostic use | Identifies applications with reliability issues that can explain client instability or user-reported crashes. |
| Caveats | In current Microsoft Graph data this app list is Endpoint Analytics app-level data, while `diagnostic_evidence.app_crashes.device_summary` is per-device. If no crashing apps are reported, the list is empty. |
| Sensitive data | Application names and reliability metrics can be sensitive. |

## Windows Protection State

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/managedDevices/{id}/windowsProtectionState` |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementConfiguration.Read.All` |
| Request | Managed-device navigation property. |
| Retrieved information | Defender/protection/firewall/malware/signature state fields where returned |
| Output mapping | `signals.security.windows_protection_state` |
| Diagnostic use | `windows-protection-risk` |
| Caveats | Field availability depends on platform, Defender integration, and Intune freshness. |
| Sensitive data | Security posture information is sensitive. |

## Windows Update Status

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/windowsUpdateStatus` |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementConfiguration.Read.All` |
| Request | Best-effort filtered collection using managed-device id, Entra device id, and deviceName field variants where supported. |
| Retrieved information | Windows update status records such as update state, error, pause/blocking/attention-required indicators where returned |
| Output mapping | `signals.updates.windows_update_status` |
| Diagnostic use | `windows-update-issues` |
| Caveats | Windows update reporting availability depends on tenant configuration and Graph filter support. Unsupported filters produce warnings. |
| Sensitive data | Update state can reveal device exposure and operational posture. |

## Entra Device Identity

| Item | Details |
| --- | --- |
| Endpoint | `GET /devices` |
| API version | `v1.0` |
| Permissions | `Directory.Read.All` or equivalent device directory read permission |
| Request | Filters by `deviceId eq '{azureADDeviceId}'`; selects id, deviceId, displayName, accountEnabled, trustType, approximateLastSignInDateTime, operatingSystem, operatingSystemVersion, isManaged, isCompliant. |
| Retrieved information | Entra device enabled/compliance/managed state, trust type, last sign-in, OS metadata |
| Output mapping | `signals.identity.entra_device` |
| Diagnostic use | `entra-device-identity-risk` |
| Caveats | Directory permissions may not be granted to the Intune collector identity. Approximate last sign-in is not real-time. |
| Sensitive data | Device identity and sign-in metadata can be sensitive. |

## Windows Autopilot Device Identity

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/windowsAutopilotDeviceIdentities` |
| API version | `v1.0` |
| Permissions | `DeviceManagementServiceConfig.Read.All` |
| Request | Best-effort filters by `azureActiveDirectoryDeviceId` and serial number. |
| Retrieved information | Autopilot registration, deployment profile, group tag, serial/manufacturer/model fields where returned |
| Output mapping | `signals.identity.autopilot_identity` |
| Diagnostic use | Context for enrollment/provisioning or duplicate/stale device diagnosis |
| Caveats | Only useful for Autopilot-managed devices. Serial number is redacted from inventory by default but may be needed for lookup. |
| Sensitive data | Serial number, group tag, and deployment profile can be sensitive. |

## Endpoint Security Intent Device States

| Item | Details |
| --- | --- |
| Endpoints | `GET /deviceManagement/intents`; `GET /deviceManagement/intents/{id}/deviceStates` |
| API version | `beta` |
| Permissions | `DeviceManagementConfiguration.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | Lists endpoint security intents up to `max_policy_objects`, then best-effort filters each device-state collection by managed-device id, Entra device id, and deviceName field variants. |
| Retrieved information | Endpoint security policy state records, status/error fields, parent intent id/display name |
| Output mapping | `signals.security.endpoint_security_intent_device_states` |
| Diagnostic use | `setting-level-policy-failures` |
| Caveats | Beta API and filter support vary. This can require multiple calls, so it is capped. |
| Sensitive data | Security policy names and states are sensitive. |

## Intune Script and Proactive Remediation Run States

| Item | Details |
| --- | --- |
| Endpoints | `GET /deviceManagement/deviceHealthScripts`; `GET /deviceManagement/deviceHealthScripts/{id}/deviceRunStates`; `GET /deviceManagement/deviceManagementScripts`; `GET /deviceManagement/deviceManagementScripts/{id}/deviceRunStates` |
| API version | `beta` |
| Permissions | `DeviceManagementConfiguration.Read.All`, `DeviceManagementManagedDevices.Read.All` |
| Request | Lists scripts/remediations up to `max_policy_objects`, then best-effort filters run states by managed-device id, Entra device id, and deviceName field variants. |
| Retrieved information | Script/remediation run result, state/status, error-like fields, parent script/remediation id/display name |
| Output mapping | `signals.management.remediation_script_states` |
| Diagnostic use | `management-action-or-script-failures` |
| Caveats | Beta API and filter support vary. Script outputs themselves are not collected unless Graph returns them in state rows. |
| Sensitive data | Script/remediation names and results can reveal internal operations. |

## Intune Troubleshooting Events

| Item | Details |
| --- | --- |
| Endpoint | `GET /users/{userId}/deviceManagementTroubleshootingEvents` |
| API version | `v1.0` |
| Permissions | `DeviceManagementManagedDevices.Read.All` plus user read permission such as `User.Read.All` when required by tenant policy |
| Request | Uses the managed device `userId`, then filters returned user-scoped events client-side for device identifiers. |
| Retrieved information | Troubleshooting event records, timestamps, operation/status/error fields where returned |
| Output mapping | `signals.troubleshooting_events` |
| Diagnostic use | `intune-troubleshooting-errors` |
| Caveats | Devices without primary user skip this source. User-scoped events may include events unrelated to the device, so the collector filters by managed-device id, Entra device id, and deviceName. |
| Sensitive data | Events can include user and operational details. |

## Endpoint Analytics Device Performance

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/userExperienceAnalyticsDevicePerformance` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementServiceConfig.Read.All` |
| Request | Tries filters using Entra device id (`azureADDeviceId`, `azureAdDeviceId`, `deviceId`) and device name where supported. |
| Retrieved information | Device performance and health scores where returned by beta Endpoint Analytics |
| Output mapping | `signals.endpoint_analytics.device_performance` |
| Diagnostic use | `endpoint-analytics-performance` |
| Caveats | Beta schema and filter support vary. The collector uses per-device filters confirmed to return useful data in the target tenant where possible. |
| Sensitive data | May contain device/user experience information. |

## Endpoint Analytics Startup History

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/userExperienceAnalyticsDeviceStartupHistory` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementServiceConfig.Read.All` |
| Request | Tries Entra-device-id and device-name filters; capped pagination. |
| Retrieved information | Startup/restart timing, history rows, and related metrics where returned |
| Output mapping | `signals.endpoint_analytics.startup_history` |
| Diagnostic use | `endpoint-analytics-performance` |
| Caveats | Beta schema and filter support vary. Startup history depends on Endpoint Analytics enrollment and data freshness. |
| Sensitive data | Can reveal device usage timing. |

## Endpoint Analytics Startup Processes

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/userExperienceAnalyticsDeviceStartupProcesses` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementServiceConfig.Read.All` |
| Request | Tries Entra-device-id and device-name filters; capped pagination. |
| Retrieved information | Startup process names, impact, duration, and related startup metrics where returned |
| Output mapping | `signals.endpoint_analytics.startup_processes` |
| Diagnostic use | `endpoint-analytics-performance` |
| Caveats | Data depends on Endpoint Analytics collection and beta filter support. |
| Sensitive data | Process names can reveal installed software and user workload. |

## Endpoint Analytics App Health - Device Performance

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/userExperienceAnalyticsAppHealthDevicePerformance` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementServiceConfig.Read.All` |
| Request | Tries Entra-device-id and device-name filters; capped pagination. |
| Retrieved information | App health performance signals by device where returned, including crash/hang/failure-like fields when available |
| Output mapping | `signals.endpoint_analytics.app_health_device_performance` |
| Diagnostic use | `endpoint-analytics-app-reliability` |
| Caveats | Beta schema and filter support vary. Some tenants may expose only aggregate data. |
| Sensitive data | Can reveal installed/running applications and stability issues. |

## Endpoint Analytics App Health - Application Performance

| Item | Details |
| --- | --- |
| Endpoint | `GET /deviceManagement/userExperienceAnalyticsAppHealthApplicationPerformance` |
| API version | `beta` |
| Permissions | `DeviceManagementManagedDevices.Read.All`, `DeviceManagementServiceConfig.Read.All` |
| Request | Tries Entra-device-id and device-name filters where supported, although this endpoint may be aggregate rather than per-device in some tenants. |
| Retrieved information | Application reliability/performance signals where returned |
| Output mapping | `signals.endpoint_analytics.app_health_application_performance` |
| Diagnostic use | `endpoint-analytics-app-reliability` |
| Caveats | Often aggregate; may not support per-device filters. Treat as supplementary evidence only. |
| Sensitive data | Application names and reliability metrics can be sensitive. |

## Error and Missing-Data Behavior

The final JSON omits raw API responses, successful endpoint telemetry, pagination details, and optional-source failures that do not help the SRE agent troubleshoot the client. Required failures, such as authentication errors or unresolved device identity, produce structured JSON findings and non-zero exit codes.
