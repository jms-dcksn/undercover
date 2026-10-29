import { useState } from "react";
import { errorMessage, post } from "./api";
import { money, outcomes } from "./format";
import type { ClaimDetail, ClaimSummary, Handler } from "./types";

interface Props {
  detail: ClaimDetail;
  runActive?: boolean;
  handlers: Handler[];
  onChange: () => Promise<void>;
}

function SignOffForm({
  handlers,
  busy,
  onSubmit,
}: Readonly<{
  handlers: Handler[];
  busy: boolean;
  onSubmit: (handler: string) => Promise<void>;
}>) {
  const [handler, setHandler] = useState<string | null>(null);
  const eligible = handlers.filter((person) => person.can_approve_over_limit);
  const selected = handler ?? eligible.at(0)?.handler_id ?? "";
  return (
    <div className="sign-off-box">
      <strong>Handler sign-off required</strong>
      <p>
        This payout exceeds the approval limit. Payment is blocked until a
        handler signs off.
      </p>
      <label htmlFor="handler">Handler</label>
      <select
        id="handler"
        value={selected}
        onChange={(event) => {
          setHandler(event.target.value);
        }}
      >
        {eligible.map((person) => (
          <option key={person.handler_id} value={person.handler_id}>
            {person.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={busy || !selected}
        onClick={() => {
          void onSubmit(selected);
        }}
      >
        Sign off payout
      </button>
    </div>
  );
}

export function Decision({
  detail,
  handlers,
  onChange,
  runActive = false,
}: Readonly<Props>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { summary, decision, sign_off: signOff, payment } = detail;
  const path = `/api/claims/${summary.claim_id}`;

  async function mutate(operation: string, body: Record<string, string>) {
    setBusy(true);
    setError(null);
    try {
      await post(`${path}/${operation}`, body);
      await onChange();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="panel content-panel decision-panel"
      aria-label="Decision and payment"
    >
      <div className="section-heading">
        <span className="eyebrow">CLAIM OUTCOME</span>
        <h2>{decision ? outcomes[decision.outcome] : "Ready for review"}</h2>
      </div>
      {decision ? (
        <>
          <div className="payout">
            <span>Payout</span>
            <strong>{money(decision.payout)}</strong>
          </div>
          <p>{decision.explanation}</p>
          <a
            href="#policy-wording"
            onClick={() => {
              document
                .querySelector<HTMLDetailsElement>("#policy-wording details")
                ?.setAttribute("open", "");
            }}
          >
            Policy section {decision.policy_section}
          </a>
          {summary.state === "waiting_for_sign_off" ? (
            <SignOffForm
              handlers={handlers}
              busy={busy}
              onSubmit={(handlerId) =>
                mutate("sign-off", { handler_id: handlerId })
              }
            />
          ) : null}
          {signOff ? (
            <p className="confirmation">
              Signed off by {signOff.handler_name}.
            </p>
          ) : null}
          {payment ? (
            <p className="confirmation">
              Simulated payment recorded: {money(payment.amount)}
            </p>
          ) : null}
          {summary.payment_status === "pending" &&
          decision.outcome === "approve" &&
          detail.run?.state !== "running" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                void mutate("payment", { amount: decision.payout });
              }}
            >
              Simulate payment
            </button>
          ) : null}
        </>
      ) : (
        <StartClaim
          summary={summary}
          disabled={busy || runActive}
          onRun={() => {
            void mutate("run", { thread_id: crypto.randomUUID() });
          }}
        />
      )}

      {busy ? (
        <p role="status" className="muted">
          Saving…
        </p>
      ) : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function StartClaim({
  summary,
  disabled,
  onRun,
}: Readonly<{ summary: ClaimSummary; disabled: boolean; onRun: () => void }>) {
  return (
    <>
      <p className="muted">
        The agent will review the evidence against the policy wording and claims
        manual and save its decision here.
      </p>
      {summary.state === "needs_handler" ? (
        <p className="error">
          Technical failure after {summary.failures} attempts.{" "}
          {summary.last_error} A handler must review this claim; no insurance
          decision was recorded.
        </p>
      ) : null}
      <button
        type="button"
        disabled={disabled || summary.state !== "waiting"}
        onClick={onRun}
      >
        {summary.state === "in_progress" ? "Agent working" : "Run claim"}
      </button>
    </>
  );
}
