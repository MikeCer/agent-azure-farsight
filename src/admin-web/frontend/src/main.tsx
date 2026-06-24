import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import Editor from "@monaco-editor/react";
import "./styles.css";

type FeatureId = "overview" | "policies" | "tool-calls" | "approvals" | "jobs" | "devices";
type Theme = "light" | "dark";

type ValidationResult = {
  status: "valid" | "invalid" | string;
  messages: string[];
};

type PolicyDocument = {
  policyId: string;
  version: string;
  status: string;
  content: string;
  contentHash: string;
  updatedAtUtc: string;
  updatedBy: string;
  validation: ValidationResult;
  notes?: string;
};

type PolicySummary = {
  policyId: string;
  activeVersion?: string;
  versions: PolicyDocument[];
};

type ToolCallByTool = {
  toolName: string;
  totalCalls: number;
  allowedCalls: number;
  deniedCalls: number;
  approvalRequiredCalls: number;
  failedCalls: number;
  lastSeenUtc?: string | null;
};

type RecentToolCall = {
  timestampUtc: string;
  toolName: string;
  decision: string;
  actor?: string | null;
  actorAppId?: string | null;
  policyId?: string | null;
  policyVersion?: string | null;
  jobId?: string | null;
  correlationId?: string | null;
  reason?: string | null;
  ruleName?: string | null;
};

type ToolCallTelemetrySummary = {
  window: string;
  totalCalls: number;
  allowedCalls: number;
  deniedCalls: number;
  approvalRequiredCalls: number;
  failedCalls: number;
  byTool: ToolCallByTool[];
  recent: RecentToolCall[];
};

type JobSummary = {
  jobId: string;
  deviceId: string;
  taskType: string;
  status: string;
  riskLevel: string;
  policyVersion?: string;
  correlationId?: string;
  incidentId?: string;
  createdAtUtc?: string;
  expiresAtUtc?: string;
  requestedBy?: { kind: string; toolName?: string };
  parameters?: Record<string, unknown>;
  resultSummary?: Record<string, unknown>;
  resultFindings?: Array<{ severity: string; code: string; message: string }>;
  approvalRequired?: boolean;
  approvalStatus?: string;
  approvalId?: string;
};

type ApprovalRecord = {
  approvalId: string;
  correlationId?: string;
  requestedAction: string;
  riskLevel: string;
  requestedBy: string;
  reason: string;
  expiresAtUtc: string;
  status?: string;
  jobId?: string | null;
  deviceId?: string | null;
  taskType?: string | null;
  createdAtUtc?: string;
  decidedBy?: string | null;
  decidedAtUtc?: string | null;
  comment?: string | null;
};

type ApprovalDetail = {
  approval: ApprovalRecord;
  jobs: JobSummary[];
};

type ArtifactMetadata = {
  artifactId: string;
  kind: string;
  name: string;
  sha256: string;
  sizeBytes: number;
};

type DeviceRecord = {
  deviceId: string;
  tenantId?: string;
  hostname?: string;
  collectorVersion?: string;
  manifestVersion?: string;
  hostnameHash?: string;
  os?: { name: string; version: string };
  lastCheckinUtc?: string;
  lastJobId?: string;
  appliedConfigVersion?: string;
};

type DeviceConfig = {
  scheduledTaskIntervalMinutes?: number;
  maxSingleRunSeconds?: number;
  checkInIntervalSeconds?: number;
  logRetentionDays?: number;
  configVersion?: string;
};

const HEARTBEAT_STALE_MINUTES = 15;
const HEARTBEAT_DEAD_MINUTES = 60;

function heartbeatStatus(lastCheckinUtc?: string): "healthy" | "stale" | "offline" | "unknown" {
  if (!lastCheckinUtc) return "unknown";
  const diff = (Date.now() - new Date(lastCheckinUtc).getTime()) / 60000;
  if (diff < HEARTBEAT_STALE_MINUTES) return "healthy";
  if (diff < HEARTBEAT_DEAD_MINUTES) return "stale";
  return "offline";
}

function minutesAgo(value?: string): string {
  if (!value) return "never";
  const diff = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (diff < 1) return "just now";
  if (diff < 60) return `${diff}m ago`;
  const h = Math.floor(diff / 60);
  const m = diff % 60;
  return m ? `${h}h ${m}m ago` : `${h}h ago`;
}

const defaultPolicyId = "farsight-tool-policy";
const defaultPolicyVersion = "2026-06-12.1";
const themeStorageKey = "farsight-admin-theme";

const STATUS_COLORS: Record<string, string> = {
  Succeeded: "status-success",
  succeeded: "status-success",
  Failed: "status-error",
  failed: "status-error",
  Expired: "status-error",
  expired: "status-error",
  waiting_approval: "status-warning",
  pending: "status-warning",
  approved: "status-success",
  denied: "status-error",
  Running: "status-running",
  running: "status-running",
  Leased: "status-running",
  leased: "status-running",
  Queued: "status-pending",
  queued: "status-pending",
  Cancelled: "status-neutral",
  cancelled: "status-neutral",
};

const features: Array<{ id: FeatureId; label: string; icon: string; description: string }> = [
  { id: "overview", label: "Overview", icon: "⌁", description: "Operational landing page and deployment health." },
  { id: "policies", label: "Policy repository", icon: "◇", description: "Version and activate AGT governance policies." },
  { id: "tool-calls", label: "Tool-call monitoring", icon: "↯", description: "Monitor SRE Agent and gateway tool activity." },
  { id: "approvals", label: "Approvals", icon: "✓", description: "Approve or deny human-gated diagnostic requests." },
  { id: "jobs", label: "Diagnostic jobs", icon: "▣", description: "Track diagnostic job lifecycle and outcomes." },
  { id: "devices", label: "Devices", icon: "◌", description: "Monitor collector heartbeats and device check-in status." },
];

function newPolicyTemplate(policyId: string, policyVersion: string) {
  return `apiVersion: governance.toolkit/v1
name: ${policyId}
version: "${policyVersion}"
default_action: deny
rules:
  - name: deny-dangerous-input
    condition: "contains_dangerous_input == true"
    action: deny
    description: "Deny arbitrary script, shell, encoded command, or free-form path input."

  - name: require-approval-for-sensitive-diagnostics
    condition: "risk_level == 'sensitive-diagnostic'"
    action: require_approval
    description: "Sensitive diagnostics require explicit approval."
`;
}

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function getInitialTheme(): Theme {
  const stored = window.localStorage.getItem(themeStorageKey);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail ?? parsed);
    } catch { /* keep raw text */ }
    throw new Error(detail || `Request failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${STATUS_COLORS[status] ?? "status-neutral"}`}>{status}</span>;
}

function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [activeFeature, setActiveFeature] = useState<FeatureId>("overview");

  // Policy state
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [selectedPolicyId, setSelectedPolicyId] = useState(defaultPolicyId);
  const [version, setVersion] = useState(defaultPolicyVersion);
  const [content, setContent] = useState("");
  const [metadata, setMetadata] = useState<PolicyDocument | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);

  // Tool-call telemetry state
  const [toolCallSummary, setToolCallSummary] = useState<ToolCallTelemetrySummary | null>(null);
  const [toolCallLoading, setToolCallLoading] = useState(false);
  const [telemetryWindow, setTelemetryWindow] = useState("24h");

  // Approval state
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const [approvalsLoading, setApprovalsLoading] = useState(false);
  const [approvalStatusFilter, setApprovalStatusFilter] = useState("pending");
  const [approvalPage, setApprovalPage] = useState(0);
  const [selectedApproval, setSelectedApproval] = useState<ApprovalDetail | null>(null);
  const [approvalDecisionComment, setApprovalDecisionComment] = useState("");

  // Jobs state
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [selectedJob, setSelectedJob] = useState<JobSummary | null>(null);
  const [jobArtifacts, setJobArtifacts] = useState<ArtifactMetadata[]>([]);
  const [downloadingArtifactId, setDownloadingArtifactId] = useState<string | null>(null);
  const [jobFilter, setJobFilter] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("all");
  const [deviceIdInput, setDeviceIdInput] = useState("");

  // Devices state
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState<DeviceRecord | null>(null);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [deviceHeartbeatFilter, setDeviceHeartbeatFilter] = useState("all");
  const [deviceConfig, setDeviceConfig] = useState<DeviceConfig>({});
  const [deviceConfigLoading, setDeviceConfigLoading] = useState(false);
  const [deviceConfigSaving, setDeviceConfigSaving] = useState(false);

  // Tool-call monitoring paging and detail
  const [byToolPage, setByToolPage] = useState(0);
  const [recentPage, setRecentPage] = useState(0);
  const [selectedCall, setSelectedCall] = useState<RecentToolCall | null>(null);

  // Shared status
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function navigateFeature(feature: FeatureId) {
    if (feature === activeFeature) return;
    setActiveFeature(feature);
    setSelectedJob(null);
    setJobArtifacts([]);
    setSelectedDevice(null);
    setSelectedApproval(null);
    window.history.pushState({ feature }, "", window.location.href);
  }

  // ── Policy functions ────────────────────────────────────────────────────────

  function loadPolicyDocument(policy: PolicySummary) {
    const active = policy.versions.find((item) => item.version === policy.activeVersion) ?? policy.versions[0];
    setSelectedPolicyId(policy.policyId);
    setVersion(active?.version ?? defaultPolicyVersion);
    setContent(active?.content ?? "");
    setMetadata(active ?? null);
    setValidation(active?.validation ?? null);
    setMessage("");
    setError("");
  }

  function startNewPolicy() {
    const policyId = `custom-policy-${new Date().toISOString().slice(0, 10)}`;
    const policyVersion = new Date().toISOString().slice(0, 10);
    navigateFeature("policies");
    setSelectedPolicyId(policyId);
    setVersion(policyVersion);
    setContent(newPolicyTemplate(policyId, policyVersion));
    setMetadata(null);
    setValidation(null);
    setMessage("New draft policy initialized. Save it to add it to the repository.");
    setError("");
  }

  async function loadPolicies() {
    setError("");
    const data = await api<PolicySummary[]>("/api/bff/policies");
    setPolicies(data);
    const first = data[0];
    if (first && !content) loadPolicyDocument(first);
  }

  async function validateCurrent() {
    setError(""); setMessage("");
    const result = await api<ValidationResult>(`/api/bff/policies/${selectedPolicyId}/validate`, {
      method: "POST", body: JSON.stringify({ content }),
    });
    setValidation(result);
    setMessage(result.status === "valid" ? "Policy is valid." : "Policy needs changes before activation.");
  }

  async function saveDraft() {
    setError(""); setMessage("");
    const saved = await api<PolicyDocument>(`/api/bff/policies/${selectedPolicyId}/versions/${version}`, {
      method: "PUT",
      body: JSON.stringify({ content, status: "draft", updatedBy: "admin-ui", notes: "Saved from admin policy editor." }),
    });
    setMetadata(saved); setValidation(saved.validation);
    setMessage("Draft saved.");
    await loadPolicies();
  }

  async function activateVersion() {
    setError(""); setMessage("");
    const activated = await api<PolicyDocument>(`/api/bff/policies/${selectedPolicyId}/versions/${version}/activate`, {
      method: "POST",
      body: JSON.stringify({ activatedBy: "admin-ui", notes: "Activated from admin policy editor." }),
    });
    setMetadata(activated); setValidation(activated.validation);
    setMessage("Policy version activated.");
    await loadPolicies();
  }

  async function deleteVersion() {
    setError(""); setMessage("");
    if (metadata?.status === "active") {
      setError("Active policy versions cannot be deleted. Activate another version first."); return;
    }
    if (!window.confirm(`Delete policy version ${selectedPolicyId}@${version}? This cannot be undone.`)) return;
    await api<{ status: string }>(`/api/bff/policies/${selectedPolicyId}/versions/${version}`, { method: "DELETE" });
    setContent(""); setMetadata(null); setValidation(null);
    setMessage("Policy version deleted.");
    await loadPolicies();
  }

  // ── Tool-call functions ─────────────────────────────────────────────────────

  async function loadToolCallSummary(window = telemetryWindow) {
    setToolCallLoading(true); setError("");
    try {
      setToolCallSummary(await api<ToolCallTelemetrySummary>(`/api/bff/telemetry/tool-calls/summary?window=${encodeURIComponent(window)}`));
      setTelemetryWindow(window);
    } finally {
      setToolCallLoading(false);
    }
  }

  async function loadApprovals(status = approvalStatusFilter) {
    setApprovalsLoading(true); setError("");
    try {
      const data = await api<{ approvals: ApprovalRecord[]; total: number }>(`/api/bff/approvals?status_filter=${encodeURIComponent(status)}`);
      setApprovals(data.approvals ?? []);
      setApprovalPage(0);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setApprovalsLoading(false);
    }
  }

  async function loadApprovalDetail(approval: ApprovalRecord) {
    setError("");
    const detail = await api<ApprovalDetail>(`/api/bff/approvals/${encodeURIComponent(approval.approvalId)}`);
    setSelectedApproval(detail);
    setApprovalDecisionComment("");
  }

  async function decideApproval(approvalId: string, decision: "approved" | "denied") {
    setError(""); setMessage("");
    await api<{ status: string; decision: string }>(`/api/bff/approvals/${encodeURIComponent(approvalId)}/decision`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        decidedAtUtc: new Date().toISOString(),
        comment: approvalDecisionComment || undefined,
      }),
    });
    setMessage(`Approval ${decision}.`);
    setSelectedApproval(null);
    await loadApprovals();
    await loadJobs().catch(() => {});
  }

  // ── Jobs functions ──────────────────────────────────────────────────────────

  const loadJobs = useCallback(async (deviceId?: string) => {
    setJobsLoading(true); setError("");
    try {
      const path = deviceId ? `/api/bff/jobs?device_id=${encodeURIComponent(deviceId)}` : "/api/bff/jobs";
      const data = await api<JobSummary[]>(path);
      setJobs(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setJobsLoading(false);
    }
  }, []);

  async function loadJobDetail(job: JobSummary) {
    setSelectedJob(job);
    setJobArtifacts([]);
    try {
      const detail = await api<{ jobId: string; status: string; summary?: Record<string, unknown> }>(
        `/api/bff/jobs/${job.jobId}`
      );
      setSelectedJob({ ...job, resultSummary: detail.summary ?? job.resultSummary, status: detail.status ?? job.status });
    } catch {
      // detail/summary refresh failure is non-fatal — keep the row data we already have
    }
    try {
      const artsData = await api<{ jobId: string; artifacts: ArtifactMetadata[] }>(`/api/bff/jobs/${job.jobId}/artifacts`);
      setJobArtifacts(artsData.artifacts ?? []);
    } catch {
      // artifact listing failure is non-fatal — section simply stays hidden
    }
  }

  async function downloadArtifact(jobId: string, artifact: ArtifactMetadata) {
    setDownloadingArtifactId(artifact.artifactId);
    setError("");
    try {
      const response = await fetch(`/api/bff/jobs/${jobId}/artifacts/${encodeURIComponent(artifact.artifactId)}/download`);
      if (!response.ok) {
        let detail = `Download failed with HTTP ${response.status}`;
        try {
          const parsed = JSON.parse(await response.text()) as { detail?: unknown };
          if (typeof parsed.detail === "string") detail = parsed.detail;
        } catch { /* keep default */ }
        throw new Error(detail);
      }
      // Prefer the filename advertised by the server, fall back to artifact metadata.
      let fileName = artifact.name || `${artifact.artifactId}.bin`;
      const disposition = response.headers.get("content-disposition");
      const match = disposition?.match(/filename="?([^"]+)"?/i);
      if (match?.[1]) fileName = match[1];
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDownloadingArtifactId(null);
    }
  }

  async function loadDevices() {
    setDevicesLoading(true); setError("");
    try {
      const data = await api<{ devices: DeviceRecord[]; total: number }>("/api/bff/devices");
      setDevices(data.devices ?? []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDevicesLoading(false);
    }
  }

  async function loadDeviceConfig(deviceId: string) {
    setDeviceConfigLoading(true);
    try {
      const cfg = await api<DeviceConfig>(`/api/bff/devices/${encodeURIComponent(deviceId)}/config`);
      setDeviceConfig(cfg ?? {});
    } catch {
      setDeviceConfig({});
    } finally {
      setDeviceConfigLoading(false);
    }
  }

  async function saveDeviceConfig(deviceId: string) {
    setDeviceConfigSaving(true); setError(""); setMessage("");
    try {
      const r = await fetch(`/api/bff/devices/${encodeURIComponent(deviceId)}/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(deviceConfig),
      });
      if (r.ok) {
        setMessage("Configuration saved. The device will receive it on its next check-in.");
        await loadDeviceConfig(deviceId);
        setTimeout(() => setMessage(""), 4000);
      } else {
        const t = await r.text();
        setError(`Save failed: ${t}`);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setDeviceConfigSaving(false);
    }
  }

  // ── Effects ─────────────────────────────────────────────────────────────────

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(themeStorageKey, theme);
  }, [theme]);

  useEffect(() => {
    window.history.replaceState({ feature: activeFeature }, "", window.location.href);
    const onPopState = (event: PopStateEvent) => {
      const nextFeature = (event.state?.feature as FeatureId | undefined) ?? "overview";
      setActiveFeature(nextFeature);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => { loadPolicies().catch((err) => setError(err.message)); }, []);

  useEffect(() => {
    if (activeFeature === "tool-calls" && toolCallSummary === null && !toolCallLoading) {
      loadToolCallSummary().catch((err) => setError(err.message));
    }
    if (activeFeature === "jobs" && jobs.length === 0 && !jobsLoading) {
      loadJobs().catch((err) => setError(err.message));
    }
    if (activeFeature === "approvals" && approvals.length === 0 && !approvalsLoading) {
      loadApprovals().catch((err) => setError(err.message));
    }
    if (activeFeature === "devices" && devices.length === 0 && !devicesLoading) {
      loadDevices().catch((err) => setError(err.message));
    }
  }, [activeFeature]);

  useEffect(() => {
    setSelectedJob(null);
    setJobArtifacts([]);
    setSelectedDevice(null);
    setSelectedApproval(null);
  }, [activeFeature]);

  // ── Filtered jobs ───────────────────────────────────────────────────────────

  const filteredJobs = jobs.filter((job) => {
    const q = jobFilter.toLowerCase();
    const matchesText = !q || job.jobId.toLowerCase().includes(q) || job.deviceId.toLowerCase().includes(q) ||
      job.taskType.toLowerCase().includes(q) || (job.correlationId ?? "").toLowerCase().includes(q);
    const matchesStatus = jobStatusFilter === "all" || job.status.toLowerCase() === jobStatusFilter.toLowerCase();
    return matchesText && matchesStatus;
  });

  const jobStatuses = ["all", ...Array.from(new Set(jobs.map((j) => j.status)))];

  // ── Filtered devices ────────────────────────────────────────────────────────

  const filteredDevices = devices.filter((d) => {
    const q = deviceFilter.toLowerCase();
    const matchesText = !q || d.deviceId.toLowerCase().includes(q) ||
      (d.hostname ?? "").toLowerCase().includes(q) ||
      (d.collectorVersion ?? "").toLowerCase().includes(q);
    const hb = heartbeatStatus(d.lastCheckinUtc);
    const matchesHb = deviceHeartbeatFilter === "all" || hb === deviceHeartbeatFilter;
    return matchesText && matchesHb;
  });

  const heartbeatCounts = {
    healthy: devices.filter((d) => heartbeatStatus(d.lastCheckinUtc) === "healthy").length,
    stale: devices.filter((d) => heartbeatStatus(d.lastCheckinUtc) === "stale").length,
    offline: devices.filter((d) => heartbeatStatus(d.lastCheckinUtc) === "offline").length,
    unknown: devices.filter((d) => heartbeatStatus(d.lastCheckinUtc) === "unknown").length,
  };

  // ── Render functions ────────────────────────────────────────────────────────

  function renderOverview() {
    return (
      <section className="feature-panel">
        <div className="feature-heading">
          <p className="eyebrow">Agent-Azure-FarSight</p>
          <h2>Governed endpoint diagnostics</h2>
          <p>
            FarSight provides a governed, policy-enforced diagnostic workflow for corporate Windows endpoints managed through
            Microsoft Intune. An Azure SRE Agent submits diagnostic job requests through an AGT gateway. The gateway evaluates
            each request against the active governance policy before forwarding to the control API. A PowerShell collector
            installed on managed devices polls the API for assigned jobs, executes only allowlisted diagnostic modules, and
            posts structured result envelopes back for SRE review.
          </p>
        </div>

        <div className="overview-section">
          <h3>Architecture</h3>
          <ol className="quickstart-steps">
            <li><strong>SRE Agent</strong> calls <code>create_diagnostic_job</code> → routed through the AGT tool gateway.</li>
            <li><strong>AGT gateway</strong> evaluates the request against the active policy (loaded from this API). Denied or approval-required calls are blocked.</li>
            <li><strong>Control API</strong> persists the job document to Cosmos DB and enqueues a session message on Service Bus.</li>
            <li><strong>Collector</strong> on the managed device checks in, receives a lease, executes the approved module, and posts results.</li>
            <li><strong>SRE Agent</strong> polls job status via <code>monitor_farsight_job</code>, then surfaces findings and artifact metadata.</li>
          </ol>
        </div>

        <div className="overview-section">
          <h3>Quick-start — what to do first</h3>
          <ol className="quickstart-steps">
            <li>Open <strong>Policy repository</strong> and verify the active <code>farsight-tool-policy</code> is present and valid.</li>
            <li>Open <strong>Devices</strong> to confirm at least one collector is checking in with a healthy heartbeat.</li>
            <li>Ask the SRE Agent to run a <code>Get-ServiceStatusSnapshot</code> or <code>Get-ConfigEvidence</code> job for a device. Approved read-only modules proceed automatically; sensitive-diagnostic modules require an approval record.</li>
            <li>Open <strong>Diagnostic jobs</strong> to monitor the job lifecycle and inspect result summaries once the collector completes.</li>
          </ol>
        </div>

        <div className="overview-section">
          <h3>Approved diagnostic modules</h3>
          <ul className="module-list">
            <li><code>Get-ServiceStatusSnapshot</code> — Windows service list and runtime status</li>
            <li><code>Get-AppHealthSnapshot</code> — Application process health and service account state</li>
            <li><code>Get-AppLogBundle</code> — Bounded application log collection (requires app scope)</li>
            <li><code>Get-AppEventSlice</code> — Windows Event Log slice by time range and provider</li>
            <li><code>Get-ConfigEvidence</code> — Registry and file system configuration evidence</li>
            <li><code>Test-AppConnectivity</code> — Network reachability and TLS certificate checks</li>
            <li><code>Get-AppDiskEvidence</code> — Bounded disk artefact sampling</li>
          </ul>
        </div>
      </section>
    );
  }

  function renderPolicyRepository() {
    return (
      <section className="policy-layout">
        <aside className="panel">
          <div className="panel-header">
            <h2>Policy repository</h2>
            <div>
              <button onClick={() => loadPolicies().catch((err) => setError(err.message))}>Refresh</button>
              <button onClick={startNewPolicy}>New policy</button>
            </div>
          </div>
          <p className="helper">The AGT gateway uses the active version of the configured policy ID.</p>
          {policies.length === 0 ? <p>No policies loaded yet.</p> : (
            <ul className="policy-list">
              {policies
                .sort((a, b) => {
                  // Active policies first (those with activeVersion)
                  const aActive = a.activeVersion ? 1 : 0;
                  const bActive = b.activeVersion ? 1 : 0;
                  if (aActive !== bActive) return bActive - aActive;
                  // Then alphabetical by policy ID
                  return a.policyId.localeCompare(b.policyId);
                })
                .map((policy) => {
                  const isActive = !!policy.activeVersion;
                  return (
                    <li key={policy.policyId} className={isActive ? "active" : ""}>
                      <button className={policy.policyId === selectedPolicyId ? "selected" : ""} onClick={() => loadPolicyDocument(policy)}>
                        <strong>{policy.policyId}</strong>
                        <span>{isActive ? `✓ Active: ${policy.activeVersion}` : "Draft"}</span>
                      </button>
                    </li>
                  );
                })}
            </ul>
          )}
        </aside>
        <section className="editor-panel">
          <div className="toolbar">
            <div className="policy-id-field">
              <label htmlFor="policyId">Policy ID</label>
              <input id="policyId" value={selectedPolicyId} onChange={(e) => setSelectedPolicyId(e.target.value)} />
            </div>
            <div>
              <label htmlFor="version">Version</label>
              <input id="version" value={version} onChange={(e) => setVersion(e.target.value)} />
            </div>
            <button onClick={() => validateCurrent().catch((err) => setError(err.message))}>Validate</button>
            <button onClick={() => saveDraft().catch((err) => setError(err.message))}>Save draft</button>
            <button className="primary" onClick={() => activateVersion().catch((err) => setError(err.message))}>Activate</button>
            <button className="danger-button" disabled={!metadata || metadata.status === "active"}
              title={metadata?.status === "active" ? "Active policy versions cannot be deleted." : "Delete this policy version."}
              onClick={() => deleteVersion().catch((err) => setError(err.message))}>Delete</button>
          </div>
          <Editor height="560px" language="yaml" theme={theme === "dark" ? "vs-dark" : "light"} value={content}
            options={{ minimap: { enabled: false }, fontSize: 14, wordWrap: "on", scrollBeyondLastLine: false }}
            onChange={(value) => setContent(value ?? "")} />
          <div className="status-grid">
            <article>
              <h3>Validation</h3>
              <p className={validation?.status === "valid" ? "valid" : "invalid"}>{validation?.status ?? "not checked"}</p>
              <ul>{(validation?.messages ?? []).map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
            <article>
              <h3>Metadata</h3>
              <p>Status: <span className="metadata-value">{metadata?.status ?? "unknown"}</span></p>
              <p>Hash: <span className="metadata-value">{metadata?.contentHash ?? "not saved"}</span></p>
              <p>Updated: <span className="metadata-value">{formatTimestamp(metadata?.updatedAtUtc)}</span></p>
              <p>Updated by: <span className="metadata-value">{metadata?.updatedBy ?? "not saved"}</span></p>
            </article>
          </div>
          {message && <p className="message">{message}</p>}
          {error && <p className="error">{error}</p>}
        </section>
      </section>
    );
  }

  function renderToolCallMonitoring() {
    const summary = toolCallSummary;
    const PAGE_SIZE = 10;

    function actorLabel(call: RecentToolCall): string {
      if (call.actorAppId) return `SRE Agent (${call.actorAppId.slice(0, 8)}…)`;
      if (call.actor && call.actor !== "unknown" && call.actor !== "workload-auth-disabled") return `Agent (${call.actor.slice(0, 8)}…)`;
      if (call.actor === "workload-auth-disabled") return "Local dev (auth disabled)";
      return "Unknown caller";
    }

    const byToolItems = summary?.byTool ?? [];
    const byToolTotal = byToolItems.length;
    const byToolPaged = byToolItems.slice(byToolPage * PAGE_SIZE, (byToolPage + 1) * PAGE_SIZE);
    const byToolPages = Math.ceil(byToolTotal / PAGE_SIZE);

    const recentItems = summary?.recent ?? [];
    const recentTotal = recentItems.length;
    const recentPaged = recentItems.slice(recentPage * PAGE_SIZE, (recentPage + 1) * PAGE_SIZE);
    const recentPages = Math.ceil(recentTotal / PAGE_SIZE);

    return (
      <>
        {selectedCall && (
          <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setSelectedCall(null); }}>
            <div className="job-detail-panel">
              <div className="panel-header">
                <h3>Tool call detail</h3>
                <button onClick={() => setSelectedCall(null)}>✕ Close</button>
              </div>
              <div className="panel-body">
                <dl className="job-dl">
                  <dt>Tool</dt><dd><strong>{selectedCall.toolName}</strong></dd>
                  <dt>Decision</dt><dd><StatusBadge status={selectedCall.decision} /></dd>
                  <dt>Actor</dt><dd>{actorLabel(selectedCall)}</dd>
                  <dt>Actor ID</dt><dd className="mono">{selectedCall.actor ?? "—"}</dd>
                  <dt>Actor App ID (Entra)</dt><dd className="mono">{selectedCall.actorAppId ?? "—"}</dd>
                  <dt>Timestamp</dt><dd>{formatTimestamp(selectedCall.timestampUtc)}</dd>
                  <dt>Policy</dt><dd>{selectedCall.policyId ?? "—"} @ {selectedCall.policyVersion ?? "—"}</dd>
                  <dt>Rule</dt><dd>{selectedCall.ruleName ?? "—"}</dd>
                  <dt>Reason</dt><dd>{selectedCall.reason ?? "—"}</dd>
                  <dt>Job ID</dt><dd className="mono">{selectedCall.jobId ?? "—"}</dd>
                  <dt>Correlation</dt><dd className="mono">{selectedCall.correlationId ?? "—"}</dd>
                </dl>
                {selectedCall.jobId && (
                  <div className="job-section">
                    <button className="primary" onClick={() => {
                      const filterValue = selectedCall.correlationId || selectedCall.jobId || "";
                      setSelectedCall(null);
                      setDeviceIdInput("");
                      setJobFilter(filterValue);
                      navigateFeature("jobs");
                      loadJobs().catch(() => {});
                    }}>View related jobs →</button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        <section className="feature-panel">
          <div className="feature-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p className="eyebrow">Tool-call monitoring</p>
              <h2>AGT gateway activity</h2>
              <p>Read-only view for tool execution volume, policy decisions, and recent SRE Agent gateway activity.</p>
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <div>
                <label htmlFor="telemetry-window" style={{ marginRight: "6px", fontSize: "0.9em" }}>Time window:</label>
                <select 
                  id="telemetry-window"
                  value={telemetryWindow} 
                  onChange={(e) => loadToolCallSummary(e.target.value).catch((err) => setError(err.message))}
                  style={{
                    padding: "6px 8px",
                    border: "1px solid var(--border)",
                    borderRadius: "3px",
                    backgroundColor: "var(--card)",
                    color: "var(--text)",
                    cursor: "pointer",
                    fontSize: "0.9em"
                  }}
                >
                  <option value="24h">Last 24 hours</option>
                  <option value="7d">Last 7 days</option>
                  <option value="30d">Last 30 days</option>
                  <option value="all">All time</option>
                </select>
              </div>
              <button onClick={() => loadToolCallSummary().catch((err) => setError(err.message))}>
                {toolCallLoading ? "Refreshing…" : "↻ Refresh"}
              </button>
            </div>
          </div>
          <div className="metric-grid">
            <article><span>Total calls</span><strong>{summary?.totalCalls ?? 0}</strong></article>
            <article><span>Allowed</span><strong>{summary?.allowedCalls ?? 0}</strong></article>
            <article><span>Denied</span><strong>{summary?.deniedCalls ?? 0}</strong></article>
            <article><span>Approval required</span><strong>{summary?.approvalRequiredCalls ?? 0}</strong></article>
            <article><span>Failed</span><strong>{summary?.failedCalls ?? 0}</strong></article>
          </div>
          <div className="table-panel">
            <div className="panel-header">
              <h3>Calls by tool</h3>
              {byToolPages > 1 && (
                <span className="jobs-count">Page {byToolPage + 1}/{byToolPages}</span>
              )}
            </div>
            {byToolTotal === 0 ? (
              <p className="empty-state">No tool-call telemetry available yet. Once the SRE Agent invokes FarSight diagnostic tools through the AGT gateway, activity will appear here.</p>
            ) : (
              <>
                <table>
                  <thead><tr><th>Tool</th><th>Total</th><th>Allowed</th><th>Denied</th><th>Approval</th><th>Failed</th><th>Last seen</th></tr></thead>
                  <tbody>
                    {byToolPaged.map((tool) => (
                      <tr key={tool.toolName}>
                        <td>{tool.toolName}</td><td>{tool.totalCalls}</td><td>{tool.allowedCalls}</td>
                        <td>{tool.deniedCalls}</td><td>{tool.approvalRequiredCalls}</td><td>{tool.failedCalls}</td>
                        <td>{formatTimestamp(tool.lastSeenUtc)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {byToolPages > 1 && (
                  <div className="paging-controls">
                    <button disabled={byToolPage === 0} onClick={() => setByToolPage(byToolPage - 1)}>← Prev</button>
                    <button disabled={byToolPage >= byToolPages - 1} onClick={() => setByToolPage(byToolPage + 1)}>Next →</button>
                  </div>
                )}
              </>
            )}
          </div>
          <div className="table-panel">
            <div className="panel-header">
              <h3>Recent calls</h3>
              {recentPages > 1 && (
                <span className="jobs-count">Page {recentPage + 1}/{recentPages}</span>
              )}
            </div>
            {recentTotal === 0 ? (
              <p className="empty-state">No recent tool calls found for the current window ({summary?.window ?? "24h"}).</p>
            ) : (
              <>
                <table className="jobs-table">
                  <thead><tr><th>Time</th><th>Tool</th><th>Decision</th><th>Actor</th><th>Policy</th><th>Correlation</th><th></th></tr></thead>
                  <tbody>
                    {recentPaged.map((call) => (
                      <tr key={`${call.timestampUtc}-${call.toolName}-${call.correlationId ?? ""}`}
                        onClick={() => setSelectedCall(call)} style={{ cursor: "pointer" }}>
                        <td>{formatTimestamp(call.timestampUtc)}</td>
                        <td>{call.toolName}</td>
                        <td><StatusBadge status={call.decision} /></td>
                        <td>{actorLabel(call)}</td>
                        <td>{call.policyId ? `${call.policyId}@${call.policyVersion ?? "?"}` : "—"}</td>
                        <td className="mono truncate">{call.correlationId ?? call.jobId ?? "—"}</td>
                        <td><button className="row-action" onClick={(e) => { e.stopPropagation(); setSelectedCall(call); }}>Details →</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {recentPages > 1 && (
                  <div className="paging-controls">
                    <button disabled={recentPage === 0} onClick={() => setRecentPage(recentPage - 1)}>← Prev</button>
                    <button disabled={recentPage >= recentPages - 1} onClick={() => setRecentPage(recentPage + 1)}>Next →</button>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      </>
    );
  }

  function renderJobDetail() {
    if (!selectedJob) return null;
    const job = selectedJob;
    return (
      <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) { setSelectedJob(null); setJobArtifacts([]); } }}>
        <div className="job-detail-panel">
          <div className="panel-header">
            <h3>Job detail</h3>
            <button onClick={() => { setSelectedJob(null); setJobArtifacts([]); }}>✕ Close</button>
          </div>
          <div className="panel-body">
          <dl className="job-dl">
            <dt>Job ID</dt><dd className="mono">{job.jobId}</dd>
            <dt>Device</dt><dd className="mono">{job.deviceId}</dd>
            <dt>Task type</dt><dd>{job.taskType}</dd>
            <dt>Status</dt><dd><StatusBadge status={job.status} /></dd>
            <dt>Risk level</dt><dd>{job.riskLevel}</dd>
            <dt>Correlation</dt><dd className="mono">{job.correlationId ?? "—"}</dd>
            <dt>Incident</dt><dd>{job.incidentId ?? "—"}</dd>
            <dt>Requested by</dt><dd>{job.requestedBy ? `${job.requestedBy.kind}${job.requestedBy.toolName ? ` / ${job.requestedBy.toolName}` : ""}` : "—"}</dd>
            <dt>Created</dt><dd>{formatTimestamp(job.createdAtUtc)}</dd>
            <dt>Expires</dt><dd>{formatTimestamp(job.expiresAtUtc)}</dd>
            <dt>Policy</dt><dd>{job.policyVersion ?? "—"}</dd>
          </dl>
          {job.parameters && Object.keys(job.parameters).length > 0 && (
            <div className="job-section">
              <h4>Parameters</h4>
              <table><tbody>
                {Object.entries(job.parameters).map(([k, v]) => (
                  <tr key={k}>
                    <td className="summary-key">{k}</td>
                    <td className="mono">{typeof v === "object" ? JSON.stringify(v) : String(v ?? "—")}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
          )}
          {(job.status === "Leased" || job.status === "Queued") && (
            <div className="job-section">
              <button className="requeue-btn" onClick={async () => {
                try {
                  const r = await fetch(`/api/bff/jobs/${job.jobId}/requeue`, { method: "POST" });
                  if (r.ok || r.status === 204) {
                    setSelectedJob({ ...job, status: "Queued" });
                    loadJobs(job.deviceId).catch(() => {});
                  } else {
                    const t = await r.text();
                    setError(`Requeue failed: ${t}`);
                  }
                } catch (e: any) { setError(e.message); }
              }}>↺ Requeue job</button>
              <span className="requeue-hint">Resets a stuck Leased job back to Queued so the collector can pick it up.</span>
            </div>
          )}
          {job.resultSummary && Object.keys(job.resultSummary).length > 0 && (
            <div className="job-section">
              <h4>Result summary</h4>
              <table><tbody>
                {Object.entries(job.resultSummary).map(([k, v]) => (
                  <tr key={k}><td className="summary-key">{k}</td><td>{String(v)}</td></tr>
                ))}
              </tbody></table>
            </div>
          )}
          {job.resultFindings && job.resultFindings.length > 0 && (
            <div className="job-section">
              <h4>Findings ({job.resultFindings.length})</h4>
              <ul className="findings-list">
                {job.resultFindings.map((f, i) => (
                  <li key={i} className={`finding finding-${f.severity}`}>
                    <span className="finding-severity">{f.severity}</span>
                    <span className="finding-code">{f.code}</span>
                    <span className="finding-msg">{f.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {jobArtifacts.length > 0 && (
            <div className="job-section">
              <h4>Artifacts ({jobArtifacts.length})</h4>
              <table>
                <thead><tr><th>ID</th><th>Kind</th><th>Name</th><th>Size</th><th>Action</th></tr></thead>
                <tbody>
                  {jobArtifacts.map((a) => (
                    <tr key={a.artifactId}>
                      <td className="mono">{a.artifactId}</td>
                      <td>{a.kind}</td>
                      <td>{a.name}</td>
                      <td>{(a.sizeBytes / 1024).toFixed(1)} KB</td>
                      <td>
                        <button
                          className="row-action"
                          disabled={downloadingArtifactId === a.artifactId}
                          onClick={() => downloadArtifact(job.jobId, a)}
                        >
                          {downloadingArtifactId === a.artifactId ? "Downloading…" : "↓ Download"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          </div>
        </div>
      </div>
    );
  }

  function renderDiagnosticJobs() {
    return (
      <>
        {selectedJob && renderJobDetail()}
        <section className="feature-panel">
          <div className="feature-heading">
            <p className="eyebrow">Diagnostic jobs</p>
            <h2>Job monitoring</h2>
            <p>Track diagnostic job lifecycle — from creation through collector execution to result summary and artifact metadata.</p>
          </div>

          {/* Filter bar */}
          <div className="jobs-toolbar">
            <div className="jobs-device-query">
              <input
                placeholder="Device ID (leave empty for all)"
                value={deviceIdInput}
                onChange={(e) => setDeviceIdInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") loadJobs(deviceIdInput || undefined).catch((err) => setError(err.message)); }}
              />
              <button onClick={() => loadJobs(deviceIdInput || undefined).catch((err) => setError(err.message))}>
                {jobsLoading ? "Loading…" : "Search"}
              </button>
              <button onClick={async () => {
                try {
                  const currentJob = selectedJob;
                  await loadJobs(deviceIdInput || undefined);
                  if (currentJob) {
                    await loadJobDetail(currentJob);
                  }
                } catch (err) {
                  setError((err as Error).message);
                }
              }}>
                Refresh
              </button>
            </div>
            <input
              className="jobs-filter"
              placeholder="Filter by job ID, device, task type, correlation…"
              value={jobFilter}
              onChange={(e) => setJobFilter(e.target.value)}
            />
            <select value={jobStatusFilter} onChange={(e) => setJobStatusFilter(e.target.value)}>
              {jobStatuses.map((s) => <option key={s} value={s}>{s === "all" ? "All statuses" : s}</option>)}
            </select>
            <span className="jobs-count">{filteredJobs.length} job{filteredJobs.length !== 1 ? "s" : ""}</span>
          </div>

          {error && <p className="error">{error}</p>}

          {jobsLoading ? (
            <p className="empty-state">Loading jobs…</p>
          ) : filteredJobs.length === 0 ? (
            <div className="empty-state-block">
              <p className="empty-state">
                {jobs.length === 0
                  ? "No jobs found. Enter a device ID to scope the query, or leave empty for recent jobs."
                  : "No jobs match the current filter."}
              </p>
            </div>
          ) : (
            <div className="table-panel">
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Task type</th>
                    <th>Device</th>
                    <th>Correlation</th>
                    <th>Risk</th>
                    <th>Created</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredJobs.map((job) => (
                    <tr
                      key={job.jobId}
                      className={selectedJob?.jobId === job.jobId ? "selected-row" : ""}
                      onClick={() => loadJobDetail(job)}
                    >
                      <td><StatusBadge status={job.status} /></td>
                      <td>{job.taskType}</td>
                      <td className="mono truncate">{job.deviceId}</td>
                      <td className="mono truncate">{job.correlationId ?? "—"}</td>
                      <td><span className={`risk-badge risk-${job.riskLevel}`}>{job.riskLevel}</span></td>
                      <td>{formatTimestamp(job.createdAtUtc)}</td>
                      <td><button className="row-action" onClick={(e) => { e.stopPropagation(); navigateFeature("jobs"); loadJobDetail(job).catch((err) => setError(err.message)); }}>Details →</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

        </section>
      </>
    );
  }

  function renderDevices() {
    const hbColors: Record<string, string> = { healthy: "status-success", stale: "status-warning", offline: "status-error", unknown: "status-neutral" };
    const hbLabels: Record<string, string> = { healthy: `✓ Online (<${HEARTBEAT_STALE_MINUTES}m)`, stale: `⚠ Stale (<${HEARTBEAT_DEAD_MINUTES}m)`, offline: "✕ Offline", unknown: "? Unknown" };
    return (
      <>
        {selectedDevice && (
          <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setSelectedDevice(null); }}>
            <div className="job-detail-panel">
              <div className="panel-header">
                <h3>Device detail</h3>
                <button onClick={() => setSelectedDevice(null)}>✕ Close</button>
              </div>
              <div className="panel-body">
              <dl className="job-dl">
                {selectedDevice.hostname && selectedDevice.hostname !== selectedDevice.deviceId && (
                  <>
                    <dt>Hostname</dt><dd><strong>{selectedDevice.hostname}</strong></dd>
                  </>
                )}
                <dt>Device ID</dt><dd className="mono">{selectedDevice.deviceId}</dd>
                <dt>Tenant</dt><dd>{selectedDevice.tenantId ?? "—"}</dd>
                <dt>Heartbeat</dt><dd>
                  <span className={`status-badge ${hbColors[heartbeatStatus(selectedDevice.lastCheckinUtc)]}`}>
                    {hbLabels[heartbeatStatus(selectedDevice.lastCheckinUtc)]}
                  </span>
                </dd>
                <dt>Last check-in</dt><dd>{formatTimestamp(selectedDevice.lastCheckinUtc)} ({minutesAgo(selectedDevice.lastCheckinUtc)})</dd>
                <dt>Collector version</dt><dd>{selectedDevice.collectorVersion ?? "—"}</dd>
                <dt>Manifest version</dt><dd>{selectedDevice.manifestVersion ?? "—"}</dd>
                <dt>OS</dt><dd>{selectedDevice.os ? `${selectedDevice.os.name} ${selectedDevice.os.version}` : "—"}</dd>
                <dt>Hostname hash</dt><dd className="mono">{selectedDevice.hostnameHash ?? "—"}</dd>
                <dt>Last job ID</dt><dd className="mono">{selectedDevice.lastJobId ?? "—"}</dd>
              </dl>
              <div className="job-section">
                <button className="primary" onClick={() => {
                  setSelectedDevice(null);
                  setDeviceIdInput(selectedDevice.deviceId);
                  navigateFeature("jobs");
                  loadJobs(selectedDevice.deviceId).catch(() => {});
                }}>View jobs for this device →</button>
              </div>

              <div className="job-section config-section">
                <div className="config-section-header">
                  <span>⚙</span>
                  <h4>Remote configuration</h4>
                </div>
                <p className="config-hint">These settings are pushed to the collector on its next check-in. The device acknowledges receipt by reporting the config version.</p>
                {deviceConfigLoading ? (
                  <p className="empty-state">Loading…</p>
                ) : (
                  <div className="device-config-form">
                    <label>
                      <span>Scheduled task interval (minutes)</span>
                      <input type="number" min={1} max={1440}
                        value={deviceConfig.scheduledTaskIntervalMinutes ?? ""}
                        placeholder="5"
                        onChange={(e) => setDeviceConfig({ ...deviceConfig, scheduledTaskIntervalMinutes: e.target.value ? parseInt(e.target.value) : undefined })} />
                    </label>
                    <label>
                      <span>Max single run (seconds)</span>
                      <input type="number" min={30} max={3600}
                        value={deviceConfig.maxSingleRunSeconds ?? ""}
                        placeholder="300"
                        onChange={(e) => setDeviceConfig({ ...deviceConfig, maxSingleRunSeconds: e.target.value ? parseInt(e.target.value) : undefined })} />
                    </label>
                    <label>
                      <span>Check-in interval (seconds)</span>
                      <input type="number" min={60} max={86400}
                        value={deviceConfig.checkInIntervalSeconds ?? ""}
                        placeholder="300"
                        onChange={(e) => setDeviceConfig({ ...deviceConfig, checkInIntervalSeconds: e.target.value ? parseInt(e.target.value) : undefined })} />
                    </label>
                    <label>
                      <span>Log retention (days)</span>
                      <input type="number" min={1} max={365}
                        value={deviceConfig.logRetentionDays ?? ""}
                        placeholder="7"
                        onChange={(e) => setDeviceConfig({ ...deviceConfig, logRetentionDays: e.target.value ? parseInt(e.target.value) : undefined })} />
                    </label>
                    <div className="config-actions">
                      <button className="requeue-btn" disabled={deviceConfigSaving}
                        onClick={() => saveDeviceConfig(selectedDevice.deviceId)}>
                        {deviceConfigSaving ? "Saving…" : "Push configuration"}
                      </button>
                      {message && <span className="config-saved">✓ {message}</span>}
                      {error && <span className="config-error">✕ {error}</span>}
                      {!message && !error && deviceConfig.configVersion && (
                        <span className="requeue-hint">
                          Pending since {new Date(deviceConfig.configVersion).toLocaleString()}.
                          {selectedDevice.appliedConfigVersion === deviceConfig.configVersion
                            ? " ✓ Applied by device."
                            : " ⏳ Waiting for device check-in."}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
              </div>
            </div>
          </div>
        )}
        <section className="feature-panel">
          <div className="feature-heading">
            <p className="eyebrow">Devices</p>
            <h2>Collector heartbeat monitor</h2>
            <p>Every collector check-in is recorded as a heartbeat. Devices that have not checked in within {HEARTBEAT_STALE_MINUTES} minutes are stale; beyond {HEARTBEAT_DEAD_MINUTES} minutes they are offline.</p>
          </div>

          <div className="metric-grid">
            <article><span>Total</span><strong>{devices.length}</strong></article>
            <article><span className="status-success">Online</span><strong>{heartbeatCounts.healthy}</strong></article>
            <article><span className="status-warning">Stale</span><strong>{heartbeatCounts.stale}</strong></article>
            <article><span className="status-error">Offline</span><strong>{heartbeatCounts.offline}</strong></article>
          </div>

          <div className="jobs-toolbar">
            <input className="jobs-filter" placeholder="Filter by device ID or collector version…"
              value={deviceFilter} onChange={(e) => setDeviceFilter(e.target.value)} />
            <select value={deviceHeartbeatFilter} onChange={(e) => setDeviceHeartbeatFilter(e.target.value)}>
              <option value="all">All heartbeats</option>
              <option value="healthy">Online only</option>
              <option value="stale">Stale only</option>
              <option value="offline">Offline only</option>
              <option value="unknown">Unknown only</option>
            </select>
            <button onClick={() => loadDevices().catch((err) => setError(err.message))}>
              {devicesLoading ? "Refreshing…" : "Refresh"}
            </button>
            <span className="jobs-count">{filteredDevices.length} device{filteredDevices.length !== 1 ? "s" : ""}</span>
          </div>

          {error && <p className="error">{error}</p>}

          {devicesLoading ? (
            <p className="empty-state">Loading devices…</p>
          ) : filteredDevices.length === 0 ? (
            <p className="empty-state">
              {devices.length === 0
                ? "No devices have checked in yet. Once a collector runs and posts a check-in, it will appear here."
                : "No devices match the current filter."}
            </p>
          ) : (
            <div className="table-panel">
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Heartbeat</th>
                    <th>Hostname</th>
                    <th>Device ID</th>
                    <th>Last check-in</th>
                    <th>Collector version</th>
                    <th>OS</th>
                    <th></th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDevices.map((d) => {
                    const hb = heartbeatStatus(d.lastCheckinUtc);
                    return (
                      <tr key={d.deviceId}
                        className={selectedDevice?.deviceId === d.deviceId ? "selected-row" : ""}
                        onClick={() => {
                          const next = selectedDevice?.deviceId === d.deviceId ? null : d;
                          setSelectedDevice(next);
                          if (next) loadDeviceConfig(next.deviceId).catch(() => {});
                        }}>
                        <td><span className={`status-badge ${hbColors[hb]}`}>{hb}</span></td>
                        <td><strong>{d.hostname ?? d.deviceId}</strong></td>
                        <td className="mono truncate">{d.deviceId}</td>
                        <td title={d.lastCheckinUtc ?? ""}>{minutesAgo(d.lastCheckinUtc)}</td>
                        <td>{d.collectorVersion ?? "—"}</td>
                        <td>{d.os ? `${d.os.name} ${d.os.version}` : "—"}</td>
                        <td><button className="row-action" onClick={(e) => { e.stopPropagation(); setDeviceFilter(d.deviceId); navigateFeature("jobs"); setDeviceIdInput(d.deviceId); loadJobs(d.deviceId).catch(() => {}); }}>Jobs →</button></td>
                        <td><button className="row-action row-action-config" onClick={(e) => { e.stopPropagation(); const next = d; setSelectedDevice(next); loadDeviceConfig(next.deviceId).catch(() => {}); }}>⚙ Configure</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </>
    );
  }

  function renderApprovals() {
    const PAGE_SIZE = 10;
    const counts = {
      pending: approvals.filter((item) => (item.status ?? "pending") === "pending").length,
      approved: approvals.filter((item) => item.status === "approved").length,
      denied: approvals.filter((item) => item.status === "denied").length,
      total: approvals.length,
    };
    const totalPages = Math.ceil(approvals.length / PAGE_SIZE);
    const paged = approvals.slice(approvalPage * PAGE_SIZE, (approvalPage + 1) * PAGE_SIZE);
    const approval = selectedApproval?.approval;

    return (
      <>
        {approval && (
          <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setSelectedApproval(null); }}>
            <div className="job-detail-panel">
              <div className="panel-header">
                <h3>Approval detail</h3>
                <button onClick={() => setSelectedApproval(null)}>✕ Close</button>
              </div>
              <div className="panel-body">
                <dl className="job-dl">
                  <dt>Approval ID</dt><dd className="mono">{approval.approvalId}</dd>
                  <dt>Status</dt><dd><StatusBadge status={approval.status ?? "pending"} /></dd>
                  <dt>Requested action</dt><dd>{approval.requestedAction}</dd>
                  <dt>Task type</dt><dd>{approval.taskType ?? "—"}</dd>
                  <dt>Device</dt><dd className="mono">{approval.deviceId ?? "—"}</dd>
                  <dt>Risk</dt><dd>{approval.riskLevel}</dd>
                  <dt>Requested by</dt><dd>{approval.requestedBy}</dd>
                  <dt>Created</dt><dd>{formatTimestamp(approval.createdAtUtc)}</dd>
                  <dt>Expires</dt><dd>{formatTimestamp(approval.expiresAtUtc)}</dd>
                  <dt>Reason</dt><dd>{approval.reason}</dd>
                  <dt>Correlation</dt><dd className="mono">{approval.correlationId ?? "—"}</dd>
                  <dt>Linked jobs</dt><dd>{selectedApproval?.jobs?.length ?? 0}</dd>
                </dl>
                {selectedApproval?.jobs && selectedApproval.jobs.length > 0 && (
                  <div className="job-section">
                    <h4>Linked jobs</h4>
                    <table>
                      <thead><tr><th>Status</th><th>Job ID</th><th>Task</th><th>Device</th></tr></thead>
                      <tbody>
                        {selectedApproval.jobs.map((job) => (
                          <tr key={job.jobId}>
                            <td><StatusBadge status={job.status} /></td>
                            <td className="mono">{job.jobId}</td>
                            <td>{job.taskType}</td>
                            <td className="mono">{job.deviceId}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {(approval.status ?? "pending") === "pending" && (
                  <div className="job-section">
                    <h4>Decision</h4>
                    <textarea
                      className="approval-comment"
                      placeholder="Optional decision comment"
                      value={approvalDecisionComment}
                      onChange={(e) => setApprovalDecisionComment(e.target.value)}
                    />
                    <div className="config-actions">
                      <button className="requeue-btn" onClick={() => decideApproval(approval.approvalId, "approved").catch((err) => setError(err.message))}>Approve</button>
                      <button className="danger-button" onClick={() => decideApproval(approval.approvalId, "denied").catch((err) => setError(err.message))}>Deny</button>
                    </div>
                  </div>
                )}
                {selectedApproval?.jobs?.[0] && (
                  <div className="job-section">
                    <button className="primary" onClick={() => {
                      const jobId = selectedApproval.jobs[0].jobId;
                      setSelectedApproval(null);
                      setJobFilter(jobId);
                      navigateFeature("jobs");
                      loadJobs().catch(() => {});
                    }}>View related job →</button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        <section className="feature-panel">
          <div className="feature-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p className="eyebrow">Human-in-the-loop governance</p>
              <h2>Approval queue</h2>
              <p>Approve or deny diagnostic requests that AGT policy requires a human to review before collector polling can lease the job.</p>
            </div>
            <button onClick={() => loadApprovals().catch((err) => setError(err.message))}>
              {approvalsLoading ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
          <div className="metric-grid">
            <article><span>Total shown</span><strong>{counts.total}</strong></article>
            <article><span>Pending</span><strong>{counts.pending}</strong></article>
            <article><span>Approved</span><strong>{counts.approved}</strong></article>
            <article><span>Denied</span><strong>{counts.denied}</strong></article>
          </div>
          <div className="jobs-toolbar">
            <select value={approvalStatusFilter} onChange={(e) => { setApprovalStatusFilter(e.target.value); loadApprovals(e.target.value).catch((err) => setError(err.message)); }}>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="denied">Denied</option>
              <option value="all">All</option>
            </select>
            <span className="jobs-count">{approvals.length} approval{approvals.length !== 1 ? "s" : ""}</span>
          </div>
          {error && <p className="error">{error}</p>}
          {message && <p className="message">{message}</p>}
          {approvalsLoading ? (
            <p className="empty-state">Loading approvals…</p>
          ) : approvals.length === 0 ? (
            <p className="empty-state">No approvals found for the selected filter.</p>
          ) : (
            <div className="table-panel">
              <div className="panel-header">
                <h3>Approval requests</h3>
                {totalPages > 1 && <span className="jobs-count">Page {approvalPage + 1}/{totalPages}</span>}
              </div>
              <table className="jobs-table">
                <thead><tr><th>Status</th><th>Action</th><th>Task</th><th>Device</th><th>Risk</th><th>Requested by</th><th>Expires</th><th></th></tr></thead>
                <tbody>
                  {paged.map((item) => (
                    <tr key={item.approvalId} onClick={() => loadApprovalDetail(item).catch((err) => setError(err.message))}>
                      <td><StatusBadge status={item.status ?? "pending"} /></td>
                      <td>{item.requestedAction}</td>
                      <td>{item.taskType ?? "—"}</td>
                      <td className="mono truncate">{item.deviceId ?? "—"}</td>
                      <td>{item.riskLevel}</td>
                      <td>{item.requestedBy}</td>
                      <td>{formatTimestamp(item.expiresAtUtc)}</td>
                      <td><button className="row-action" onClick={(e) => { e.stopPropagation(); loadApprovalDetail(item).catch((err) => setError(err.message)); }}>Details →</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {totalPages > 1 && (
                <div className="paging-controls">
                  <button disabled={approvalPage === 0} onClick={() => setApprovalPage(approvalPage - 1)}>← Prev</button>
                  <button disabled={approvalPage >= totalPages - 1} onClick={() => setApprovalPage(approvalPage + 1)}>Next →</button>
                </div>
              )}
            </div>
          )}
        </section>
      </>
    );
  }

  function renderActiveFeature() {
    if (activeFeature === "overview") return renderOverview();
    if (activeFeature === "policies") return renderPolicyRepository();
    if (activeFeature === "tool-calls") return renderToolCallMonitoring();
    if (activeFeature === "approvals") return renderApprovals();
    if (activeFeature === "jobs") return renderDiagnosticJobs();
    if (activeFeature === "devices") return renderDevices();
    return null;
  }

  return (
    <main className="portal-shell">
      <header className="portal-topbar">
        <div className="portal-brand">
          <span className="waffle" aria-hidden="true">▦</span>
          <strong>Agent-Azure-FarSight</strong>
        </div>

        <button className="theme-toggle" type="button" aria-pressed={theme === "dark"}
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          <span aria-hidden="true">{theme === "dark" ? "☾" : "☼"}</span>
          {theme === "dark" ? "Dark" : "Light"}
        </button>
      </header>

      <div className="portal-body">
        <aside className="resource-menu" aria-label="Admin console blade navigation">
          <div className="resource-menu-title">
            <span className="resource-glyph" aria-hidden="true">◆</span>
            <div>
              <strong>FarSight Admin</strong>
              <small>Container App console</small>
            </div>
          </div>
          <nav>
            {features.map((feature) => (
              <button key={feature.id} className={activeFeature === feature.id ? "selected" : ""}
                  onClick={() => navigateFeature(feature.id)}>
                <span className="nav-icon" aria-hidden="true">{feature.icon}</span>
                <span>{feature.label}</span>
              </button>
            ))}
          </nav>
        </aside>

        <section className="portal-content">
          <div className="breadcrumb">Home &gt; Agent-Azure-FarSight &gt; Admin</div>
          <section className="resource-header">
            <div className="resource-title">
              <span className="resource-icon" aria-hidden="true">▣</span>
              <div>
                <h1>Admin and monitoring console</h1>
                <p>Governed diagnostics, policy management, and operational visibility.</p>
              </div>
            </div>
          </section>
          <section className="blade-content">
            {renderActiveFeature()}
          </section>
        </section>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
