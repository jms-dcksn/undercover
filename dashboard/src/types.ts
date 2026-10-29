export type QueueState =
  | "waiting"
  | "in_progress"
  | "waiting_for_sign_off"
  | "decided"
  | "needs_handler";
export type Outcome = "approve" | "decline" | "refer";
export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type RecordData = Record<string, JsonValue>;

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  plan: string;
  claim_type: string;
  summary: string;
  amount_claimed: string;
  state: QueueState;
  outcome: Outcome | null;
  payout: string | null;
  failures: number;
  last_error: string | null;
  payment_status: "not_due" | "pending" | "blocked" | "paid";
}

export interface Decision {
  outcome: Outcome;
  payout: string;
  explanation: string;
  policy_section: number;
}

export interface ClaimDetail {
  summary: ClaimSummary;
  claim: RecordData & {
    story: string;
    documents: { name: string; type: string; content: string }[];
    items: { description: string; category: string; amount: number }[];
  };
  policy: RecordData;
  plan: RecordData;
  plan_terms: RecordData;
  customer: RecordData;
  decision: Decision | null;
  sign_off: { handler_name: string; created_at: string } | null;
  payment: { amount: string; created_at: string } | null;
  run: { id: string; state: "running" | "completed" | "failed" } | null;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  can_approve_over_limit: boolean;
}

export interface ActivityEvent {
  id: number;
  kind: string;
  message: string;
  created_at: string;
}

export interface TextDocument {
  text: string;
}

export type TaskState = "todo" | "in_progress" | "done" | "left_for_handler";

export interface QueueTask {
  attempts: number;
  failures: number;
  error: string | null;
  claim_id: string;
  description: string;
  state: TaskState;
  admitted: boolean;
  position: number;
  result: string | null;
}

export interface QueueRun {
  id: string;
  state: "running" | "completed" | "failed";
  mode: "queue" | "named";
  claim_limit: number | null;
  snapshot: string[];
  tasks: QueueTask[];
  summary: string | null;
  error: string | null;
}

export interface Instructions extends TextDocument {
  queue: string;
  claim: string;
}

export interface SectionRead {
  id: number;
  run_id: string;
  document: "wording" | "manual";
  version: string;
  section: number;
  heading: string;
  text: string;
}
