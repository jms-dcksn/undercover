import { useState } from "react";
import { useResource } from "./api";
import { Claim } from "./Claim";
import { states } from "./format";
import { Queue } from "./Queue";
import type { ClaimSummary, Handler, TextDocument } from "./types";
import "./styles.css";

function whileWorking(claims: ClaimSummary[]) {
  return claims.some((claim) => claim.state === "in_progress");
}

function Instructions() {
  const resource = useResource<TextDocument>("/api/agent/instructions");
  return (
    <section className="panel instructions">
      <span className="eyebrow">READ ONLY</span>
      <h1>Agent instructions</h1>
      <p className="muted">
        The exact instructions the agent receives for each claim.
      </p>
      {resource.error ? (
        <p className="error" role="alert">
          {resource.error}
        </p>
      ) : (
        <pre className="document-text">
          {resource.data?.text ?? "Loading instructions…"}
        </pre>
      )}
    </section>
  );
}

export function App() {
  const claims = useResource<ClaimSummary[]>("/api/claims", whileWorking);
  const handlers = useResource<Handler[]>("/api/handlers");
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState("claims");
  const selectedId = selected ?? claims.data?.[0]?.claim_id ?? "";

  return (
    <>
      <header className="app-header">
        <a className="wordmark" href="/">
          <span className="brand-mark" aria-hidden="true">
            u
          </span>
          UnderCover<span className="wordmark-caption">TRAVEL INSURANCE</span>
        </a>
        <nav aria-label="Main navigation">
          <button
            type="button"
            className={page === "claims" ? "nav-active" : ""}
            onClick={() => {
              setPage("claims");
            }}
          >
            Claims
          </button>
          <button
            type="button"
            className={page === "instructions" ? "nav-active" : ""}
            onClick={() => {
              setPage("instructions");
            }}
          >
            Agent instructions
          </button>
        </nav>
        <span className="pilot-label">Claims pilot</span>
      </header>
      <main className="workspace">
        {page === "instructions" ? (
          <Instructions />
        ) : (
          <>
            <div className="workspace-heading">
              <div>
                <span className="eyebrow">THE CLAIMS DESK</span>
                <h1>
                  Every claim. <em>A clear next step.</em>
                </h1>
                <p className="muted">
                  Review the evidence, follow the agent's work and keep claims
                  moving.
                </p>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  void claims.reload();
                }}
              >
                Refresh queue
              </button>
            </div>
            <section className="metrics" aria-label="Queue overview">
              {Object.entries(states).map(([state, text]) => (
                <div className={`metric ${state}`} key={state}>
                  <span>{text}</span>
                  <strong>
                    {claims.data?.filter((claim) => claim.state === state)
                      .length ?? 0}
                  </strong>
                </div>
              ))}
            </section>
            {claims.error ? (
              <p className="error error-banner" role="alert">
                {claims.error}
              </p>
            ) : null}
            {handlers.error ? (
              <p className="error error-banner" role="alert">
                Handlers could not be loaded: {handlers.error}
              </p>
            ) : null}
            {claims.data ? (
              <div className="desk">
                <Queue
                  claims={claims.data}
                  selected={selectedId}
                  onSelect={setSelected}
                />
                {selectedId ? (
                  <Claim
                    key={selectedId}
                    id={selectedId}
                    handlers={handlers.data ?? []}
                    onChange={claims.reload}
                  />
                ) : (
                  <section className="panel content-panel">
                    <h2>No claims in the queue</h2>
                    <p>New claims will appear here.</p>
                  </section>
                )}
              </div>
            ) : (
              <p role="status" className="empty">
                {claims.error
                  ? "Check the backend connection, then refresh the queue."
                  : "Loading the claims desk…"}
              </p>
            )}
          </>
        )}
      </main>
      <footer className="app-footer">
        <span>UnderCover Travel Insurance</span>
        <span>All amounts in USD · Payments are simulated</span>
      </footer>
    </>
  );
}
