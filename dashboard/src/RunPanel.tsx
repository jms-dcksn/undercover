import { useState } from "react";
import { errorMessage, post } from "./api";
import type { QueueRun, TaskState } from "./types";

const taskLabels: Record<TaskState, string> = {
  todo: "To do",
  in_progress: "In progress",
  done: "Done",
  left_for_handler: "Left for handler",
};
const runLabels = {
  running: "Run in progress",
  completed: "Run completed",
  failed: "Run failed",
};

function RunControls({
  active,
  onChange,
}: Readonly<{ active: boolean; onChange: () => Promise<void> }>) {
  const [limit, setLimit] = useState("5");
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const valid =
    all || (/^[1-9]\d*$/.test(limit) && Number.isSafeInteger(Number(limit)));
  const disabled = active || busy;
  let button = "Run queue";
  if (active) button = "Queue running";
  if (busy) button = "Starting…";

  async function start() {
    setBusy(true);
    setFailure(null);
    try {
      await post("/api/agent/runs", {
        thread_id: crypto.randomUUID(),
        claim_id: null,
        claim_limit: all ? null : Number(limit),
      });
      await onChange();
    } catch (caught) {
      setFailure(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form
        aria-label="Queue scope"
        className="run-controls"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid && !disabled) void start();
        }}
      >
        <label htmlFor="claim-cap">Claim limit</label>
        <input
          id="claim-cap"
          type="number"
          min="1"
          step="1"
          value={limit}
          disabled={all || disabled}
          onChange={(event) => {
            setLimit(event.target.value);
          }}
          aria-invalid={!valid}
        />
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={all}
            disabled={disabled}
            onChange={(event) => {
              setAll(event.target.checked);
            }}
          />
          All waiting claims
        </label>
        <button type="submit" disabled={!valid || disabled}>
          {button}
        </button>
      </form>
      {!valid ? (
        <p className="error">Enter a positive whole-number claim limit.</p>
      ) : null}
      {failure ? (
        <p className="error" role="alert">
          {failure}
        </p>
      ) : null}
    </div>
  );
}

function RunProgress({ run }: Readonly<{ run: QueueRun }>) {
  let scope =
    run.claim_limit === null ? "Uncapped" : `Limit ${String(run.claim_limit)}`;
  if (run.mode === "named") scope = "Named claim";
  const finished = run.tasks.filter(
    (task) => task.state === "done" || task.state === "left_for_handler",
  ).length;
  return (
    <div className="run-progress" aria-live="polite">
      <p>
        <strong>{runLabels[run.state]}</strong>
        {" · "}
        {finished} finished
        {" · "}
        {run.tasks.filter((task) => task.admitted).length} admitted
        {" · "}
        {scope}
      </p>
      {run.tasks.length ? (
        <ol className="task-list">
          {run.tasks.map((task) => (
            <li key={task.claim_id}>
              <span className={`status task-${task.state}`}>
                {taskLabels[task.state]}
              </span>
              <span className="identifier">{task.claim_id}</span>{" "}
              {task.description}
              {task.admitted ? (
                <p className="muted">
                  {task.attempts} attempts · {task.failures} technical failures
                </p>
              ) : null}
              {task.error ? (
                <p className="muted">Last technical error: {task.error}</p>
              ) : null}
              {task.result ? (
                <p className="muted task-result">{task.result}</p>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">No tasks in this run.</p>
      )}
      {run.error ? (
        <p className="error" role="alert">
          {run.error}
        </p>
      ) : null}
      {run.summary ? <p className="run-summary">{run.summary}</p> : null}
    </div>
  );
}

export function RunPanel({
  run,
  error,
  onChange,
}: Readonly<{
  run: QueueRun | null;
  error: string | null;
  onChange: () => Promise<void>;
}>) {
  return (
    <section className="panel content-panel run-panel" aria-label="Queue run">
      <div className="run-heading">
        <div>
          <span className="eyebrow">QUEUE AGENT</span>
          <h2>Work the waiting queue</h2>
        </div>
        <RunControls active={run?.state === "running"} onChange={onChange} />
      </div>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {run ? (
        <RunProgress run={run} />
      ) : (
        <p className="muted">No stored queue run.</p>
      )}
    </section>
  );
}
