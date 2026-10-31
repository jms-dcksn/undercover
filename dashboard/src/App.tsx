import { useCallback, useEffect, useState } from "react";
import { useResource } from "./useResource";
import { Claim } from "./Claim";
import { states } from "./format";
import { RunPanel } from "./RunPanel";
import { Queue } from "./Queue";
import type {
  ClaimSummary,
  Handler,
  Instructions as InstructionSets,
  QueueRun,
} from "./types";
import "./styles.css";

function whileWorking(claims: ClaimSummary[]) {
  return claims.some((claim) => claim.state === "in_progress");
}

function Instructions() {
  const resource = useResource<InstructionSets>("/api/agent/instructions");
  if (resource.error)
    return (
      <p className="error" role="alert">
        {resource.error}
      </p>
    );
  const content = resource.data ? (
    <>
      <h2>Running the queue</h2>
      <pre className="document-text">{resource.data.queue}</pre>
      <h2>Working a claim</h2>
      <pre className="document-text">{resource.data.claim}</pre>
    </>
  ) : (
    <p>Loading instructions…</p>
  );
  return (
    <section className="panel instructions">
      <span className="eyebrow">READ ONLY</span>
      <h1>Agent instructions</h1>
      <p className="muted">
        The exact instructions supplied to the queue and claim agents.
      </p>
      {content}
    </section>
  );
}

export function App() {
  const parent = useResource<QueueRun | null>(
    "/api/agent/runs/latest",
    (run) => run?.state === "running",
  );
  const active = parent.data?.state === "running";
  const pollQueue = useCallback(
    (data: ClaimSummary[]) => active || whileWorking(data),
    [active],
  );
  const claims = useResource<ClaimSummary[]>("/api/claims", pollQueue);
  const reloadClaims = claims.reload;
  useEffect(() => {
    void reloadClaims();
  }, [parent.data, reloadClaims]);
  async function refresh() {
    await Promise.all([claims.reload(), parent.reload()]);
  }
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
                  void refresh();
                }}
              >
                Refresh queue
              </button>
            </div>
            <RunPanel
              run={parent.data}
              error={parent.error}
              onChange={refresh}
            />
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
                    onChange={refresh}
                    queueRunning={active}
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
