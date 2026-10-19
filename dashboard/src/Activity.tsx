import { label, timestamp } from "./format";
import type { ActivityEvent } from "./types";

const eventLabels = new Map([
  ["tool_started", "Started"],
  ["tool_finished", "Done"],
  ["tool_error", "Failed"],
]);

export function Activity({
  events,
  running,
}: Readonly<{
  events: ActivityEvent[];
  running: boolean;
}>) {
  return (
    <section className="panel content-panel" aria-label="Agent activity">
      <div className="section-heading">
        <span className="eyebrow">OBSERVABLE WORK</span>
        <h2>
          Agent activity{" "}
          {running ? <span className="live-label">Live</span> : null}
        </h2>
      </div>
      {running ? (
        <p className="running" role="status">
          <span className="activity-dot" />
          The agent is working on this claim.
        </p>
      ) : null}
      {events.length === 0 ? (
        <p className="muted">
          Activity will appear when this claim is started.
        </p>
      ) : (
        <ol className="timeline">
          {events.map((event) => (
            <li
              key={event.id}
              className={
                event.kind === "failed" || event.kind === "tool_error"
                  ? "activity-error"
                  : ""
              }
            >
              <time dateTime={event.created_at}>
                {timestamp(event.created_at)}
              </time>
              <div>
                <small className="event-state">
                  {eventLabels.get(event.kind) ?? label(event.kind)}
                </small>
                <span>{event.message}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
