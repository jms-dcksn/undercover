import type { Outcome, QueueState } from "./types";

export const outcomes: Record<Outcome, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

export const states: Record<QueueState, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_sign_off: "Waiting for sign-off",
  decided: "Decided",
  needs_handler: "Needs handler",
};

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});
export function money(value: string | number) {
  return currency.format(Number(value));
}
export function label(value: string) {
  return value.replaceAll("_", " ");
}
export function timestamp(value: string) {
  return new Date(value).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
