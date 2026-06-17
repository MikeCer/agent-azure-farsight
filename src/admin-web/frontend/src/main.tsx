import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import Editor from "@monaco-editor/react";
import "./styles.css";

type FeatureId = "overview" | "policies" | "tool-calls" | "jobs" | "devices";
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
  policyId?: string | null;
  policyVersion?: string | null;
  jobId?: string | null;
  correlationId?: string | null;
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
  resultSummary?: Record<string, unknown>;
  resultFindings?: Array<{ severity: string; code: string; message: string }>;
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
  collectorVersion?: string;
  manifestVersion?: string;
  hostnameHash?: string;
  os?: { name: string; version: string };
  lastCheckinUtc?: string;
  lastJobId?: string;
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

  // Jobs state
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [selectedJob, setSelectedJob] = useState<JobSummary | null>(null);
  const [jobArtifacts, setJobArtifacts] = useState<ArtifactMetadata[]>([]);
  const [jobFilter, setJobFilter] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("all");
  const [deviceIdInput, setDeviceIdInput] = useState("");

  // Devices state
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState<DeviceRecord | null>(null);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [deviceHeartbeatFilter, setDeviceHeartbeatFilter] = useState("all");

  // Shared status
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

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
    setActiveFeature("policies");
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

  async function loadToolCallSummary() {
    setToolCallLoading(true); setError("");
    try {
      setToolCallSummary(await api<ToolCallTelemetrySummary>("/api/bff/telemetry/tool-calls/summary"));
    } finally {
      setToolCallLoading(false);
    }
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
      const artsData = await api<{ jobId: string; artifacts: ArtifactMetadata[] }>(`/api/bff/jobs/${job.jobId}/artifacts`);
      setJobArtifacts(artsData.artifacts ?? []);
    } catch {
      // detail fetch failure is non-fatal — show what we have
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

  // ── Effects ─────────────────────────────────────────────────────────────────

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(themeStorageKey, theme);
  }, [theme]);

  useEffect(() => { loadPolicies().catch((err) => setError(err.message)); }, []);

  useEffect(() => {
    if (activeFeature === "tool-calls" && toolCallSummary === null && !toolCallLoading) {
      loadToolCallSummary().catch((err) => setError(err.message));
    }
    if (activeFeature === "jobs" && jobs.length === 0 && !jobsLoading) {
      loadJobs().catch((err) => setError(err.message));
    }
    if (activeFeature === "devices" && devices.length === 0 && !devicesLoading) {
      loadDevices().catch((err) => setError(err.message));
    }
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
    const matchesText = !q || d.deviceId.toLowerCase().includes(q) || (d.hostnameHash ?? "").toLowerCase().includes(q) ||
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
          <p className="eyebrow">Overview</p>
          <h2>FarSight operations at a glance</h2>
          <p>Choose a feature from the console menu to manage governance policies, monitor tool-call activity, or inspect diagnostic job history.</p>
        </div>
        <div className="overview-strip">
          <article>
            <span className="icon-badge">◇</span>
            <strong>Governance first</strong>
            <p>Policy edits stay versioned and auditable before gateway enforcement changes.</p>
          </article>
          <article>
            <span className="icon-badge">↯</span>
            <strong>Tool-call monitoring</strong>
            <p>Gateway activity, policy decisions, and SRE Agent tool-call history.</p>
          </article>
          <article>
            <span className="icon-badge">▣</span>
            <strong>Diagnostic jobs</strong>
            <p>Full lifecycle view — from creation through collector execution to result summary.</p>
          </article>
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
            <button onClick={startNewPolicy}>New policy</button>
          </div>
          <p className="helper">The AGT gateway uses the active version of the configured policy ID.</p>
          {policies.length === 0 ? <p>No policies loaded yet.</p> : (
            <ul className="policy-list">
              {policies.map((policy) => (
                <li key={policy.policyId}>
                  <button className={policy.policyId === selectedPolicyId ? "selected" : ""} onClick={() => loadPolicyDocument(policy)}>
                    <strong>{policy.policyId}</strong>
                    <span>Active: {policy.activeVersion ?? "none"}</span>
                  </button>
                </li>
              ))}
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
    return (
      <section className="feature-panel">
        <div className="feature-heading">
          <p className="eyebrow">Tool-call monitoring</p>
          <h2>AGT gateway activity</h2>
          <p>Read-only view for tool execution volume, policy decisions, and recent SRE Agent gateway activity.</p>
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
            <button onClick={() => loadToolCallSummary().catch((err) => setError(err.message))}>
              {toolCallLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          {!summary || summary.byTool.length === 0 ? (
            <p className="empty-state">No tool-call telemetry available yet. Future versions will populate this from AGT/tool gateway audit events.</p>
          ) : (
            <table>
              <thead><tr><th>Tool</th><th>Total</th><th>Allowed</th><th>Denied</th><th>Approval</th><th>Failed</th><th>Last seen</th></tr></thead>
              <tbody>
                {summary.byTool.map((tool) => (
                  <tr key={tool.toolName}>
                    <td>{tool.toolName}</td><td>{tool.totalCalls}</td><td>{tool.allowedCalls}</td>
                    <td>{tool.deniedCalls}</td><td>{tool.approvalRequiredCalls}</td><td>{tool.failedCalls}</td>
                    <td>{formatTimestamp(tool.lastSeenUtc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="table-panel">
          <h3>Recent calls</h3>
          {!summary || summary.recent.length === 0 ? (
            <p className="empty-state">No recent tool calls found for the current window ({summary?.window ?? "24h"}).</p>
          ) : (
            <table>
              <thead><tr><th>Time</th><th>Tool</th><th>Decision</th><th>Actor</th><th>Policy</th><th>Correlation</th></tr></thead>
              <tbody>
                {summary.recent.map((call) => (
                  <tr key={`${call.timestampUtc}-${call.toolName}-${call.correlationId ?? ""}`}>
                    <td>{formatTimestamp(call.timestampUtc)}</td><td>{call.toolName}</td><td>{call.decision}</td>
                    <td>{call.actor ?? "unknown"}</td>
                    <td>{call.policyId ? `${call.policyId}@${call.policyVersion ?? "?"}` : "unknown"}</td>
                    <td>{call.correlationId ?? call.jobId ?? "none"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    );
  }

  function renderJobDetail() {
    if (!selectedJob) return null;
    const job = selectedJob;
    return (
      <aside className="job-detail-panel">
        <div className="panel-header">
          <h3>Job detail</h3>
          <button onClick={() => { setSelectedJob(null); setJobArtifacts([]); }}>✕ Close</button>
        </div>
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

        {job.resultSummary && Object.keys(job.resultSummary).length > 0 && (
          <div className="job-section">
            <h4>Result summary</h4>
            <table>
              <tbody>
                {Object.entries(job.resultSummary).map(([k, v]) => (
                  <tr key={k}><td className="summary-key">{k}</td><td>{String(v)}</td></tr>
                ))}
              </tbody>
            </table>
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
              <thead><tr><th>ID</th><th>Kind</th><th>Name</th><th>Size</th></tr></thead>
              <tbody>
                {jobArtifacts.map((a) => (
                  <tr key={a.artifactId}>
                    <td className="mono">{a.artifactId}</td>
                    <td>{a.kind}</td>
                    <td>{a.name}</td>
                    <td>{(a.sizeBytes / 1024).toFixed(1)} KB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </aside>
    );
  }

  function renderDiagnosticJobs() {
    return (
      <section className="jobs-layout">
        <div className="jobs-main">
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
                      <td><button className="row-action">Details →</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {selectedJob && renderJobDetail()}
      </section>
    );
  }

  function renderDevices() {
    const hbColors: Record<string, string> = { healthy: "status-success", stale: "status-warning", offline: "status-error", unknown: "status-neutral" };
    const hbLabels: Record<string, string> = { healthy: `✓ Online (<${HEARTBEAT_STALE_MINUTES}m)`, stale: `⚠ Stale (<${HEARTBEAT_DEAD_MINUTES}m)`, offline: "✕ Offline", unknown: "? Unknown" };
    return (
      <section className="jobs-layout">
        <div className="jobs-main">
          <div className="feature-heading">
            <p className="eyebrow">Devices</p>
            <h2>Collector heartbeat monitor</h2>
            <p>Every collector check-in is recorded as a heartbeat. Devices that have not checked in within {HEARTBEAT_STALE_MINUTES} minutes are stale; beyond {HEARTBEAT_DEAD_MINUTES} minutes they are offline.</p>
          </div>

          {/* Heartbeat summary */}
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
                    <th>Device ID</th>
                    <th>Last check-in</th>
                    <th>Collector version</th>
                    <th>Manifest version</th>
                    <th>OS</th>
                    <th>Last job</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDevices.map((d) => {
                    const hb = heartbeatStatus(d.lastCheckinUtc);
                    return (
                      <tr key={d.deviceId}
                        className={selectedDevice?.deviceId === d.deviceId ? "selected-row" : ""}
                        onClick={() => setSelectedDevice(selectedDevice?.deviceId === d.deviceId ? null : d)}>
                        <td><span className={`status-badge ${hbColors[hb]}`}>{hb}</span></td>
                        <td className="mono truncate">{d.deviceId}</td>
                        <td title={d.lastCheckinUtc ?? ""}>{minutesAgo(d.lastCheckinUtc)}</td>
                        <td>{d.collectorVersion ?? "—"}</td>
                        <td>{d.manifestVersion ?? "—"}</td>
                        <td>{d.os ? `${d.os.name} ${d.os.version}` : "—"}</td>
                        <td className="mono truncate">{d.lastJobId ?? "—"}</td>
                        <td><button className="row-action" onClick={(e) => { e.stopPropagation(); setDeviceFilter(d.deviceId); setActiveFeature("jobs"); setDeviceIdInput(d.deviceId); loadJobs(d.deviceId).catch(() => {}); }}>Jobs →</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Device detail panel */}
        {selectedDevice && (
          <aside className="job-detail-panel">
            <div className="panel-header">
              <h3>Device detail</h3>
              <button onClick={() => setSelectedDevice(null)}>✕ Close</button>
            </div>
            <dl className="job-dl">
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
                setActiveFeature("jobs");
                loadJobs(selectedDevice.deviceId).catch(() => {});
              }}>View jobs for this device →</button>
            </div>
          </aside>
        )}
      </section>
    );
  }

  function renderActiveFeature() {
    if (activeFeature === "overview") return renderOverview();
    if (activeFeature === "policies") return renderPolicyRepository();
    if (activeFeature === "tool-calls") return renderToolCallMonitoring();
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
          <label className="blade-search">
            <span aria-hidden="true">⌕</span>
            <input placeholder="Search menu" />
          </label>
          <nav>
            {features.map((feature) => (
              <button key={feature.id} className={activeFeature === feature.id ? "selected" : ""}
                onClick={() => setActiveFeature(feature.id)}>
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
            <button className="close-blade" type="button" aria-label="Close blade">×</button>
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
