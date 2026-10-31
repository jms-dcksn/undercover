import { useCallback } from "react";
import { Activity } from "./Activity";
import { useResource } from "./useResource";
import { Decision } from "./Decision";
import { label, money, states } from "./format";
import { ClaimRecords, RecordFields } from "./Records";
import type {
  ActivityEvent,
  ClaimDetail,
  Handler,
  TextDocument,
  SectionRead,
} from "./types";

function whileRunning(data: ClaimDetail) {
  return data.run?.state === "running";
}

export function Claim({
  id,
  handlers,
  onChange,
  queueRunning = false,
}: Readonly<{
  id: string;
  handlers: Handler[];
  onChange: () => Promise<void>;
  queueRunning?: boolean;
}>) {
  const pollClaim = useCallback(
    (data: ClaimDetail) => queueRunning || whileRunning(data),
    [queueRunning],
  );
  const resource = useResource<ClaimDetail>(`/api/claims/${id}`, pollClaim);
  const running = resource.data?.run?.state === "running";
  const pollActivity = useCallback(() => running, [running]);
  const activity = useResource<ActivityEvent[]>(
    `/api/claims/${id}/activity`,
    pollActivity,
  );
  const sections = useResource<SectionRead[]>(
    `/api/claims/${id}/sections`,
    pollActivity,
  );
  const wording = useResource<TextDocument>("/api/policy-wording");

  async function refresh() {
    await Promise.all([
      resource.reload(),
      activity.reload(),
      sections.reload(),
      onChange(),
    ]);
  }

  if (!resource.data)
    return (
      <section className="panel content-panel">
        <p role={resource.error ? "alert" : "status"}>
          {resource.error ?? "Loading claim…"}
        </p>
        <button
          type="button"
          onClick={() => {
            void resource.reload();
          }}
        >
          Retry
        </button>
      </section>
    );
  const detail = resource.data;
  const summary = detail.summary;

  return (
    <article className="claim-detail" aria-label={`Claim ${id}`}>
      {resource.error ? (
        <p role="alert" className="error">
          {resource.error}
        </p>
      ) : null}
      <header className="claim-heading">
        <div>
          <p className="eyebrow identifier">
            {id} / {label(summary.claim_type)}
          </p>
          <h2>{summary.customer_name}</h2>
          <p>{summary.summary}</p>
        </div>
        <div className="claim-heading-right">
          <span className={`status ${summary.state}`}>
            {states[summary.state]}
          </span>
          <span className="muted">Amount claimed</span>
          <strong className="amount">{money(summary.amount_claimed)}</strong>
        </div>
      </header>
      <div className="detail-columns">
        <div className="claim-evidence">
          <ClaimRecords claim={detail.claim} />
          <section className="panel content-panel">
            <h2>Claim record</h2>
            <RecordFields
              data={Object.fromEntries(
                Object.entries(detail.claim).filter(
                  ([key]) =>
                    !["story", "documents", "items", "status"].includes(key),
                ),
              )}
            />
          </section>
          <section className="panel content-panel">
            <h2>Policy and plan</h2>
            <RecordFields data={detail.policy} />
            <details className="document">
              <summary>Plan terms and add-ons</summary>
              <RecordFields data={{ ...detail.plan, ...detail.plan_terms }} />
            </details>
          </section>
          <section className="panel content-panel">
            <h2>Customer and claim history</h2>
            <RecordFields data={detail.customer} />
          </section>
          <section className="panel content-panel" id="policy-wording">
            <details>
              <summary className="document-title">Full policy wording</summary>
              {wording.error ? (
                <p className="error" role="alert">
                  {wording.error}
                </p>
              ) : (
                <pre className="document-text">
                  {wording.data?.text ?? "Loading wording…"}
                </pre>
              )}
            </details>
          </section>
        </div>
        <div className="claim-actions">
          <Decision
            detail={detail}
            handlers={handlers}
            onChange={refresh}
            runActive={queueRunning}
          />
          <ReadSections reads={sections.data ?? []} error={sections.error} />
          <Activity events={activity.data ?? []} running={running} />
          {activity.error ? (
            <p className="error" role="alert">
              {activity.error}
            </p>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function ReadSections({
  reads,
  error,
}: Readonly<{ reads: SectionRead[]; error: string | null }>) {
  return (
    <section className="panel content-panel">
      <h2>Sections read</h2>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {reads.length ? (
        reads.map((section) => (
          <details className="document" key={section.id}>
            <summary>
              {section.document === "manual"
                ? "Claims manual"
                : "Policy wording"}{" "}
              {section.version} · Section {section.section}
            </summary>
            <p className="muted identifier">Attempt {section.run_id}</p>
            <pre className="document-text">{section.text}</pre>
          </details>
        ))
      ) : (
        <p className="muted">No sections read yet.</p>
      )}
    </section>
  );
}
