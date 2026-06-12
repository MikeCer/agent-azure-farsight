import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const pages = [
  "Dashboard",
  "Device details",
  "Job search",
  "Approval queue",
  "Module catalog",
  "Configuration",
  "KQL shortcuts"
];

function App() {
  return (
    <main className="shell">
      <section>
        <p className="eyebrow">Agent-Azure-FarSight</p>
        <h1>Admin and monitoring console</h1>
        <p>
          Skeleton React shell for governed remote diagnostics. The FastAPI BFF will provide Entra-authenticated
          configuration and proxy admin calls to the control API.
        </p>
      </section>
      <section className="cards">
        {pages.map((page) => (
          <article key={page}>
            <h2>{page}</h2>
            <p>Placeholder view boundary.</p>
          </article>
        ))}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
