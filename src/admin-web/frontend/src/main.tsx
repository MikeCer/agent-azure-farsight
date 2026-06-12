import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import Editor from "@monaco-editor/react";
import "./styles.css";

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

const defaultPolicyId = "farsight-tool-policy";

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function App() {
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [selectedPolicyId, setSelectedPolicyId] = useState(defaultPolicyId);
  const [version, setVersion] = useState("2026-06-12.1");
  const [content, setContent] = useState("");
  const [metadata, setMetadata] = useState<PolicyDocument | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const activeSummary = useMemo(
    () => policies.find((policy) => policy.policyId === selectedPolicyId),
    [policies, selectedPolicyId],
  );

  async function loadPolicies() {
    setError("");
    const data = await api<PolicySummary[]>("/api/bff/policies");
    setPolicies(data);
    const first = data[0];
    if (first) {
      setSelectedPolicyId(first.policyId);
      const active = first.versions.find((item) => item.version === first.activeVersion) ?? first.versions[0];
      if (active) {
        setVersion(active.version);
        setContent(active.content);
        setMetadata(active);
        setValidation(active.validation);
      }
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

  useEffect(() => {
    loadPolicies().catch((err) => setError(err.message));
  }, []);

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Agent-Azure-FarSight</p>
        <h1>Admin and monitoring console</h1>
        <p>
          Manage governed diagnostics, approvals, module policy, and operational configuration. Policy changes are stored
          as versioned FarSight documents and evaluated by the AGT-backed gateway before tool execution.
        </p>
      </section>

      <section className="policy-layout">
        <aside className="panel">
          <h2>Policy repository</h2>
          {policies.length === 0 ? (
            <p>No policies loaded yet.</p>
          ) : (
            <ul className="policy-list">
              {policies.map((policy) => (
                <li key={policy.policyId}>
                  <button
                    className={policy.policyId === selectedPolicyId ? "selected" : ""}
                    onClick={() => {
                      const active = policy.versions.find((item) => item.version === policy.activeVersion) ?? policy.versions[0];
                      setSelectedPolicyId(policy.policyId);
                      setVersion(active?.version ?? "");
                      setContent(active?.content ?? "");
                      setMetadata(active ?? null);
                      setValidation(active?.validation ?? null);
                    }}
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
            <div>
              <label htmlFor="version">Version</label>
              <input id="version" value={version} onChange={(event) => setVersion(event.target.value)} />
            </div>
            <button onClick={() => validateCurrent().catch((err) => setError(err.message))}>Validate</button>
            <button onClick={() => saveDraft().catch((err) => setError(err.message))}>Save draft</button>
            <button className="primary" onClick={() => activateVersion().catch((err) => setError(err.message))}>Activate</button>
          </div>

          <Editor
            height="560px"
            language="yaml"
            theme="vs-dark"
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
              <p>Status: {metadata?.status ?? "unknown"}</p>
              <p>Hash: {metadata?.contentHash ?? "not saved"}</p>
              <p>Updated: {metadata?.updatedAtUtc ?? "not saved"}</p>
            </article>
          </div>

          {message && <p className="message">{message}</p>}
          {error && <p className="error">{error}</p>}
          <p className="note">
            Production authorization is still enforced server-side. This UI is the editing surface; activation must remain
            auditable and role-gated by the FarSight API/BFF.
          </p>
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
