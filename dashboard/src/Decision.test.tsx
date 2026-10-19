import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { first, handlers, makeDetail, second } from "../test-data";
import { Activity } from "./Activity";
import { errorMessage, request } from "./api";
import { Decision } from "./Decision";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("signs off with the selected eligible handler", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
  const changed = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("fetch", fetcher);
  render(
    <Decision
      detail={makeDetail(second)}
      handlers={handlers}
      onChange={changed}
    />,
  );
  expect(screen.queryByRole("option", { name: "Read Only" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Handler"), {
    target: { value: "H2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign off payout" }));
  await waitFor(() => {
    expect(changed).toHaveBeenCalledOnce();
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/api/claims/TEST-02/sign-off",
    expect.objectContaining({ body: JSON.stringify({ handler_id: "H2" }) }),
  );
});

it("keeps payment unavailable without an eligible handler", () => {
  render(
    <Decision
      detail={makeDetail(second)}
      handlers={[]}
      onChange={async () => {
        await Promise.resolve();
      }}
    />,
  );
  expect(
    screen.getByRole("button", { name: "Sign off payout" }),
  ).toHaveProperty("disabled", true);
});

it("simulates an approved unpaid claim and shows backend errors", async () => {
  const approved = makeDetail({
    ...first,
    state: "decided",
    outcome: "approve",
    payout: "420.00",
    payment_status: "pending",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "A handler must sign off." }), {
        status: 409,
      }),
    ),
  );
  render(<Decision detail={approved} handlers={handlers} onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Simulate payment" }));
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "A handler must sign off.",
  );
});

it("shows saved sign-off and payment without offering another payment", () => {
  const paid = makeDetail({
    ...second,
    state: "decided",
    payment_status: "paid",
  });
  paid.sign_off = { handler_name: "Dana Handler", created_at: "2026-10-19" };
  paid.payment = { amount: "1250.00", created_at: "2026-10-19" };
  render(<Decision detail={paid} handlers={handlers} onChange={vi.fn()} />);
  expect(screen.getByText("Signed off by Dana Handler.")).toBeDefined();
  expect(
    screen.getByText("Simulated payment recorded: $1,250.00"),
  ).toBeDefined();
  expect(screen.queryByRole("button", { name: "Simulate payment" })).toBeNull();
});

it("shows failed activity without hidden reasoning", () => {
  render(
    <Activity
      running={false}
      events={[
        {
          id: 1,
          kind: "failed",
          message: "Run failed. Retry the claim.",
          created_at: "2026-10-19T12:00:00Z",
        },
      ]}
    />,
  );
  expect(screen.getByText("Run failed. Retry the claim.")).toBeDefined();
});

it("handles non-string backend errors and unexpected thrown values", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: [] }), { status: 422 }),
      ),
  );
  await expect(request("/api/test")).rejects.toThrow("Request failed (422).");
  expect(errorMessage("unrecognized")).toBe(
    "The request could not be completed.",
  );
});
