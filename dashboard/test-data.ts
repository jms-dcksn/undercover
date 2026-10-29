import type { ClaimDetail, ClaimSummary, Handler } from "./src/types";

export const first: ClaimSummary = {
  claim_id: "TEST-01",
  customer_name: "Alex Test",
  plan: "premium",
  claim_type: "trip_delay",
  summary: "An overnight carrier delay",
  amount_claimed: "420.00",
  state: "waiting",
  outcome: null,
  payout: null,
  failures: 0,
  last_error: null,
  payment_status: "not_due",
};
export const second: ClaimSummary = {
  ...first,
  claim_id: "TEST-02",
  customer_name: "Sam Test",
  state: "waiting_for_sign_off",
  amount_claimed: "1250.00",
  outcome: "approve",
  payout: "1250.00",
  payment_status: "blocked",
};
export const handlers: Handler[] = [
  {
    handler_id: "H1",
    name: "Dana Handler",
    role: "Claims handler",
    can_approve_over_limit: true,
  },
  {
    handler_id: "H2",
    name: "Other Handler",
    role: "Claims handler",
    can_approve_over_limit: true,
  },
  {
    handler_id: "H3",
    name: "Read Only",
    role: "Trainee",
    can_approve_over_limit: false,
  },
];

export function makeDetail(summary: ClaimSummary = first): ClaimDetail {
  return {
    summary,
    claim: {
      claim_id: summary.claim_id,
      story: "My flight was canceled and I stayed overnight.",
      items: [
        {
          description: "Airport hotel",
          category: "accommodation",
          amount: 420,
        },
      ],
      documents: [
        {
          name: "Hotel receipt",
          type: "receipt",
          content: "A full itemized hotel receipt.",
        },
      ],
    },
    policy: {
      policy_id: "POL-TEST",
      trip: { destination: "Rome" },
      travelers: ["Alex Test"],
      active: true,
      canceled: false,
    },
    plan: { plan: "premium", limit: 800 },
    plan_terms: { add_ons: [], deductible: null },
    customer: {
      name: summary.customer_name,
      previous_claims: [{ summary: "A previous baggage claim" }],
    },
    decision: summary.outcome
      ? {
          outcome: summary.outcome,
          payout: summary.payout ?? "0.00",
          explanation:
            "The documented loss is covered. Eligible expenses are payable under section 3.",
          policy_section: 3,
        }
      : null,
    sign_off: null,
    payment: null,
    run: null,
  };
}
