import { useState } from "react";
import { money, states } from "./format";
import type { ClaimSummary } from "./types";

interface Props {
  claims: ClaimSummary[];
  selected: string;
  onSelect: (id: string) => void;
}

export function Queue({ claims, selected, onSelect }: Readonly<Props>) {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("all");
  const filtered = claims.filter(
    (claim) =>
      (state === "all" || claim.state === state) &&
      `${claim.claim_id} ${claim.customer_name} ${claim.summary}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );

  return (
    <aside className="queue panel" aria-label="Claims queue">
      <div className="queue-heading">
        <h2>Claims queue</h2>
        <span className="count">{claims.length}</span>
      </div>
      <div className="queue-filters">
        <label className="sr-only" htmlFor="search">
          Search claims
        </label>
        <input
          id="search"
          type="search"
          placeholder="Search claims or customers"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
        <label className="sr-only" htmlFor="state-filter">
          Filter by status
        </label>
        <select
          id="state-filter"
          value={state}
          onChange={(event) => {
            setState(event.target.value);
          }}
        >
          <option value="all">All statuses</option>
          {Object.entries(states).map(([value, text]) => (
            <option value={value} key={value}>
              {text}
            </option>
          ))}
        </select>
      </div>
      <div className="queue-list">
        {filtered.length === 0 ? (
          <p className="empty">No claims match.</p>
        ) : (
          filtered.map((claim) => (
            <button
              type="button"
              className={`queue-item ${selected === claim.claim_id ? "selected" : ""}`}
              key={claim.claim_id}
              aria-pressed={selected === claim.claim_id}
              onClick={() => {
                onSelect(claim.claim_id);
              }}
            >
              <span className="queue-item-top">
                <span className="identifier">{claim.claim_id}</span>
                <span className={`status ${claim.state}`}>
                  {states[claim.state]}
                </span>
              </span>
              <strong>{claim.customer_name}</strong>
              <span className="queue-summary">{claim.summary}</span>
              <span className="queue-item-bottom">
                <span className="plan-name">{claim.plan}</span>
                <span className="amount">{money(claim.amount_claimed)}</span>
              </span>
            </button>
          ))
        )}
      </div>
      <p className="queue-footer">
        {filtered.length} of {claims.length} claims
      </p>
    </aside>
  );
}
