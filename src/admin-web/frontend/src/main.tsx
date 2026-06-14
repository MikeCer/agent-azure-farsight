import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import Editor from "@monaco-editor/react";
import "./styles.css";

type FeatureId = "overview" | "policies" | "tool-calls" | "jobs" | "devices" | "approvals" | "configuration" | "audit";
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

const defaultPolicyId = "farsight-tool-policy";
const defaultPolicyVersion = "2026-06-12.1";
const themeStorageKey = "farsight-admin-theme";

const features: Array<{ id: FeatureId; label: string; icon: string; description: string }> = [
  { id: "overview", label: "Overview", icon: "⌁", description: "Operational landing page and deployment health." },
  { id: "policies", label: "Policy repository", icon: "◇", description: "Version and activate AGT governance policies." },
  { id: "tool-calls", label: "Tool-call monitoring", icon: "↯", description: "Monitor SRE Agent and gateway tool activity." },
  { id: "jobs", label: "Diagnostic jobs", icon: "▣", description: "Track diagnostic job lifecycle and outcomes." },
  { id: "devices", label: "Devices", icon: "◌", description: "Inspect collector check-ins and endpoint state." },
  { id: "approvals", label: "Approvals", icon: "✓", description: "Review approval-gated diagnostic actions." },
  { id: "configuration", label: "Configuration", icon: "⚙", description: "Manage runtime and retention settings." },
  { id: "audit", label: "Audit", icon: "◎", description: "Review security-relevant administrative events." },
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
  if (!value) {
    return "not available";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function getInitialTheme(): Theme {
  const stored = window.localStorage.getItem(themeStorageKey);
  if (stored === "light" || stored === "dark") {
    return stored;
  }
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
    } catch {
      // Keep the original response text for non-JSON errors.
    }
    throw new Error(detail || `Request failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [activeFeature, setActiveFeature] = useState<FeatureId>("overview");
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [selectedPolicyId, setSelectedPolicyId] = useState(defaultPolicyId);
  const [version, setVersion] = useState(defaultPolicyVersion);
  const [content, setContent] = useState("");
  const [metadata, setMetadata] = useState<PolicyDocument | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [toolCallSummary, setToolCallSummary] = useState<ToolCallTelemetrySummary | null>(null);
  const [toolCallLoading, setToolCallLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

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
    if (first && !content) {
      loadPolicyDocument(first);
    }
  }

  async function loadToolCallSummary() {
    setToolCallLoading(true);
    setError("");
    try {
      setToolCallSummary(await api<ToolCallTelemetrySummary>("/api/bff/telemetry/tool-calls/summary"));
    } finally {
      setToolCallLoading(false);
    }
  }

  async function validateCurrent() {
    setError("");
    setMessage("");
    const result = await api<ValidationResult>(`/api/bff/policies/${selectedPolicyId}/validate`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    setValidation(result);
    setMessage(result.status === "valid" ? "Policy is valid." : "Policy needs changes before activation.");
  }

  async function saveDraft() {
    setError("");
    setMessage("");
    const saved = await api<PolicyDocument>(`/api/bff/policies/${selectedPolicyId}/versions/${version}`, {
      method: "PUT",
      body: JSON.stringify({ content, status: "draft", updatedBy: "admin-ui", notes: "Saved from admin policy editor." }),
    });
    setMetadata(saved);
    setValidation(saved.validation);
    setMessage("Draft saved.");
    await loadPolicies();
  }

  async function activateVersion() {
    setError("");
    setMessage("");
    const activated = await api<PolicyDocument>(`/api/bff/policies/${selectedPolicyId}/versions/${version}/activate`, {
      method: "POST",
      body: JSON.stringify({ activatedBy: "admin-ui", notes: "Activated from admin policy editor." }),
    });
    setMetadata(activated);
    setValidation(activated.validation);
    setMessage("Policy version activated.");
    await loadPolicies();
  }

  async function deleteVersion() {
    setError("");
    setMessage("");
    if (metadata?.status === "active") {
      setError("Active policy versions cannot be deleted. Activate another version first.");
      return;
    }
    if (!window.confirm(`Delete policy version ${selectedPolicyId}@${version}? This cannot be undone.`)) {
      return;
    }
    await api<{ status: string }>(`/api/bff/policies/${selectedPolicyId}/versions/${version}`, { method: "DELETE" });
    setContent("");
    setMetadata(null);
    setValidation(null);
    setMessage("Policy version deleted.");
    await loadPolicies();
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(themeStorageKey, theme);
  }, [theme]);

  useEffect(() => {
    loadPolicies().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (activeFeature === "tool-calls" && toolCallSummary === null && !toolCallLoading) {
      loadToolCallSummary().catch((err) => setError(err.message));
    }
  }, [activeFeature]);

  function renderOverview() {
    return (
      <section className="feature-panel">
        <div className="feature-heading">
          <p className="eyebrow">Overview</p>
          <h2>FarSight operations at a glance</h2>
          <p>
            Choose a feature from the console menu. Policy management is one workspace in the broader FarSight operations
            console; monitoring, approvals, devices, jobs, configuration, and audit views will fill in as the platform matures.
          </p>
        </div>
        <div className="overview-strip">
          <article>
            <span className="icon-badge">◇</span>
            <strong>Governance first</strong>
            <p>Policy edits stay versioned and auditable before gateway enforcement changes.</p>
          </article>
          <article>
            <span className="icon-badge">↯</span>
            <strong>Tool calls next</strong>
            <p>Telemetry contracts are ready for AGT/tool gateway audit aggregation.</p>
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
          <p className="helper">
            The repository can hold multiple policy documents and versions. The AGT gateway uses the active version of the
            configured policy ID.
          </p>
          {policies.length === 0 ? (
            <p>No policies loaded yet.</p>
          ) : (
            <ul className="policy-list">
              {policies.map((policy) => (
                <li key={policy.policyId}>
                  <button
                    className={policy.policyId === selectedPolicyId ? "selected" : ""}
                    onClick={() => loadPolicyDocument(policy)}
                  >
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
              <input id="policyId" value={selectedPolicyId} onChange={(event) => setSelectedPolicyId(event.target.value)} />
            </div>
            <div>
              <label htmlFor="version">Version</label>
              <input id="version" value={version} onChange={(event) => setVersion(event.target.value)} />
            </div>
            <button onClick={() => validateCurrent().catch((err) => setError(err.message))}>Validate</button>
            <button onClick={() => saveDraft().catch((err) => setError(err.message))}>Save draft</button>
            <button className="primary" onClick={() => activateVersion().catch((err) => setError(err.message))}>Activate</button>
            <button
              className="danger-button"
              disabled={!metadata || metadata.status === "active"}
              title={metadata?.status === "active" ? "Active policy versions cannot be deleted." : "Delete this policy version."}
              onClick={() => deleteVersion().catch((err) => setError(err.message))}
            >
              Delete
            </button>
          </div>

          <Editor
            height="560px"
            language="yaml"
            theme={theme === "dark" ? "vs-dark" : "light"}
            value={content}
            options={{ minimap: { enabled: false }, fontSize: 14, wordWrap: "on", scrollBeyondLastLine: false }}
            onChange={(value) => setContent(value ?? "")}
          />

          <div className="status-grid">
            <article>
              <h3>Validation</h3>
              <p className={validation?.status === "valid" ? "valid" : "invalid"}>{validation?.status ?? "not checked"}</p>
              <ul>
                {(validation?.messages ?? []).map((item) => <li key={item}>{item}</li>)}
              </ul>
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
              {toolCallLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
          {!summary || summary.byTool.length === 0 ? (
            <p className="empty-state">No tool-call telemetry is available yet. Future versions will populate this from AGT/tool gateway audit events.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Total</th>
                  <th>Allowed</th>
                  <th>Denied</th>
                  <th>Approval</th>
                  <th>Failed</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {summary.byTool.map((tool) => (
                  <tr key={tool.toolName}>
                    <td>{tool.toolName}</td>
                    <td>{tool.totalCalls}</td>
                    <td>{tool.allowedCalls}</td>
                    <td>{tool.deniedCalls}</td>
                    <td>{tool.approvalRequiredCalls}</td>
                    <td>{tool.failedCalls}</td>
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
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Tool</th>
                  <th>Decision</th>
                  <th>Actor</th>
                  <th>Policy</th>
                  <th>Correlation</th>
                </tr>
              </thead>
              <tbody>
                {summary.recent.map((call) => (
                  <tr key={`${call.timestampUtc}-${call.toolName}-${call.correlationId ?? ""}`}>
                    <td>{formatTimestamp(call.timestampUtc)}</td>
                    <td>{call.toolName}</td>
                    <td>{call.decision}</td>
                    <td>{call.actor ?? "unknown"}</td>
                    <td>{call.policyId ? `${call.policyId}@${call.policyVersion ?? "unknown"}` : "unknown"}</td>
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

  function renderPlaceholder(feature: { label: string; description: string }) {
    return (
      <section className="feature-panel">
        <div className="feature-heading">
          <p className="eyebrow">{feature.label}</p>
          <h2>{feature.label}</h2>
          <p>{feature.description}</p>
        </div>
        <p className="empty-state">This feature area is reserved in the admin console shell and will be implemented in a later milestone.</p>
      </section>
    );
  }

  function renderActiveFeature() {
    if (activeFeature === "overview") {
      return renderOverview();
    }
    if (activeFeature === "policies") {
      return renderPolicyRepository();
    }
    if (activeFeature === "tool-calls") {
      return renderToolCallMonitoring();
    }
    return renderPlaceholder(features.find((feature) => feature.id === activeFeature)!);
  }

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Agent-Azure-FarSight</p>
          <h1>Admin and monitoring console</h1>
          <p>
            Manage governed diagnostics, approvals, module policy, and operational configuration. Policy changes are stored
            as versioned FarSight documents and evaluated by the AGT-backed gateway before tool execution.
          </p>
        </div>
        <button
          className="theme-toggle"
          type="button"
          aria-pressed={theme === "dark"}
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          <span aria-hidden="true">{theme === "dark" ? "☾" : "☼"}</span>
          {theme === "dark" ? "Dark" : "Light"}
        </button>
      </section>

      <div className="console-layout">
        <nav className="feature-nav" aria-label="Admin console features">
          {features.map((feature) => (
            <button
              key={feature.id}
              className={activeFeature === feature.id ? "selected" : ""}
              onClick={() => setActiveFeature(feature.id)}
            >
              <span className="nav-icon" aria-hidden="true">{feature.icon}</span>
              <strong>{feature.label}</strong>
              <span>{feature.description}</span>
            </button>
          ))}
        </nav>

        <section className="console-content">
          {renderActiveFeature()}
          {message && activeFeature !== "policies" && <p className="message">{message}</p>}
          {error && <p className="error">{error}</p>}
          <p className="note">
            Production authorization is still enforced server-side. This UI is the editing surface; activation and future
            monitoring views must remain auditable and role-gated by the FarSight API/BFF.
          </p>
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
