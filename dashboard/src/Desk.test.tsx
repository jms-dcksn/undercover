import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { first, handlers, makeDetail, second } from "../test-data";
import { App } from "./App";
import { ClaimRecords } from "./Records";

const responses = new Map<string, unknown>();

beforeEach(() => {
  responses.clear();
  responses.set("/api/agent/runs/latest", null);
  responses.set("/api/claims/TEST-01/sections", []);
  responses.set("/api/claims/TEST-02/sections", []);
  responses.set("/api/claims", [first, second]);
  responses.set("/api/handlers", handlers);
  responses.set("/api/claims/TEST-01", makeDetail());
  responses.set("/api/claims/TEST-02", makeDetail(second));
  responses.set("/api/claims/TEST-01/activity", []);
  responses.set("/api/claims/TEST-02/activity", []);
  responses.set("/api/policy-wording", {
    text: "## 3. Trip Delay\nFull policy wording.",
  });
  responses.set("/api/agent/instructions", {
    text: "Read all evidence. Use the policy wording.",
    claim: "Read all evidence. Use the policy wording.",
    queue: "Plan the waiting queue.",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(responses.has(path) ? responses.get(path) : {}),
        ),
      ),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the complete claims desk and supporting records", async () => {
  render(<App />);
  const claim = await screen.findByRole("article", { name: "Claim TEST-01" });
  expect(
    within(claim).getByText("My flight was canceled and I stayed overnight."),
  ).toBeDefined();
  expect(within(claim).getByText("A previous baggage claim")).toBeDefined();
  fireEvent.click(within(claim).getByText("Hotel receipt"));
  expect(
    within(claim).getByText("A full itemized hotel receipt."),
  ).toBeDefined();
  expect(within(claim).getAllByText("$420.00").length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "Run claim" })).toBeDefined();
  expect(
    screen.getByText("Activity will appear when this claim is started."),
  ).toBeDefined();
});

it("filters, searches and selects a claim requiring sign-off", async () => {
  render(<App />);
  await screen.findByRole("article", { name: "Claim TEST-01" });
  fireEvent.change(screen.getByLabelText("Search claims"), {
    target: { value: "Sam" },
  });
  const queue = screen.getByRole("complementary", { name: "Claims queue" });
  expect(within(queue).queryByText("Alex Test")).toBeNull();
  fireEvent.click(within(queue).getByRole("button", { name: /TEST-02/ }));
  await screen.findByRole("article", { name: "Claim TEST-02" });
  expect(screen.getByText("Handler sign-off required")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Simulate payment" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Filter by status"), {
    target: { value: "decided" },
  });
  expect(within(queue).getByText("No claims match.")).toBeDefined();
});

it("shows read-only instructions and returns to the desk", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Agent instructions" }));
  expect(
    await screen.findByText("Read all evidence. Use the policy wording."),
  ).toBeDefined();
  expect(screen.queryByRole("textbox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Claims" }));
  expect(
    await screen.findByRole("article", { name: "Claim TEST-01" }),
  ).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Refresh queue" }));
});

it("starts a claim and renders actual activity", async () => {
  render(<App />);
  await screen.findByRole("button", { name: "Run claim" });
  const working = makeDetail({ ...first, state: "in_progress" });
  working.run = { id: "run-1", state: "running" };
  responses.set("/api/claims/TEST-01", working);
  responses.set("/api/claims", [working.summary, second]);
  responses.set("/api/claims/TEST-01/activity", [
    {
      id: 1,
      kind: "tool_started",
      message: "Read policy wording",
      created_at: "2026-10-19T12:00:00Z",
    },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Run claim" }));
  expect(
    await screen.findByText("The agent is working on this claim."),
  ).toBeDefined();
  expect(await screen.findByText("Read policy wording")).toBeDefined();
  expect(screen.getByRole("button", { name: "Agent working" })).toHaveProperty(
    "disabled",
    true,
  );
  const finished = makeDetail({
    ...first,
    state: "decided",
    outcome: "refer",
    payout: "0.00",
  });
  finished.run = { id: "run-1", state: "completed" };
  responses.set("/api/claims/TEST-01", finished);
  responses.set("/api/claims", [finished.summary, second]);
  responses.set("/api/claims/TEST-01/activity", [
    {
      id: 2,
      kind: "completed",
      message: "Agent run completed.",
      created_at: "2026-10-19T12:01:00Z",
    },
  ]);
  await waitFor(
    () => {
      expect(screen.getByText("Agent run completed.")).toBeDefined();
    },
    { timeout: 4000 },
  );
});

it("shows empty and failed queue states with refresh", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("Backend unavailable")),
  );
  render(<App />);
  expect(await screen.findAllByRole("alert")).toHaveLength(3);
  cleanup();
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      let data: unknown = handlers;
      if (path === "/api/claims") data = [];
      if (path === "/api/agent/runs/latest") data = null;
      return Promise.resolve(new Response(JSON.stringify(data)));
    }),
  );
  render(<App />);
  expect(await screen.findByText("No claims in the queue")).toBeDefined();
});

it("displays instruction and claim-loading errors", async () => {
  const fetcher = vi.fn((path: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          path === "/api/claims/TEST-01" || path === "/api/agent/instructions"
            ? { detail: "Unavailable" }
            : responses.get(path),
        ),
        {
          status:
            path === "/api/claims/TEST-01" || path === "/api/agent/instructions"
              ? 503
              : 200,
        },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  expect(await screen.findByRole("button", { name: "Retry" })).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  fireEvent.click(screen.getByRole("button", { name: "Agent instructions" }));
  expect(await screen.findByRole("alert", { name: "" })).toBeDefined();
});

it("shows a claim without supporting documents", () => {
  render(
    <ClaimRecords
      claim={{ story: "Receipt missing.", items: [], documents: [] }}
    />,
  );
  expect(screen.getByText("No supporting documents attached.")).toBeDefined();
});

it("shows technical handler work and filters it separately from referrals", async () => {
  const failed = {
    ...first,
    state: "needs_handler" as const,
    failures: 2,
    last_error: "Provider failed twice.",
  };
  responses.set("/api/claims", [failed, second]);
  responses.set("/api/claims/TEST-01", makeDetail(failed));
  render(<App />);
  await screen.findByRole("article", { name: "Claim TEST-01" });
  expect(screen.getByText(/Technical failure after 2 attempts/)).toBeDefined();
  expect(screen.getByRole("button", { name: "Run claim" })).toHaveProperty(
    "disabled",
    true,
  );
  fireEvent.change(screen.getByLabelText("Filter by status"), {
    target: { value: "needs_handler" },
  });
  const queue = screen.getByRole("complementary", { name: "Claims queue" });
  expect(within(queue).queryByText("Sam Test")).toBeNull();
});

it("shows exact section read evidence with version and attempt", async () => {
  responses.set("/api/claims/TEST-01/sections", [
    {
      id: 1,
      run_id: "attempt-one",
      document: "manual",
      version: "2026.2",
      section: 7,
      heading: "Interpretation notes",
      text: "Exact manual text including a table.",
    },
    {
      id: 2,
      run_id: "attempt-one",
      document: "wording",
      version: "2026.1",
      section: 5,
      heading: "Baggage",
      text: "Exact wording text.",
    },
  ]);
  render(<App />);
  expect(
    await screen.findByText("Claims manual 2026.2 · Section 7"),
  ).toBeDefined();
  expect(
    screen.getByText("Exact manual text including a table."),
  ).toBeDefined();
  expect(screen.getAllByText("Attempt attempt-one")).toHaveLength(2);
});

it("polls parent work between claims and retains its terminal summary on refresh", async () => {
  const active = {
    id: "parent",
    state: "running",
    mode: "queue",
    claim_limit: 5,
    snapshot: ["TEST-01"],
    tasks: [],
    error: null,
    summary: null,
  };
  responses.set("/api/agent/runs/latest", active);
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Queue running" }),
  ).toHaveProperty("disabled", true);
  const finished = {
    ...active,
    state: "completed",
    summary: "One saved decision; four outside cap.",
  };
  responses.set("/api/agent/runs/latest", finished);
  expect(
    await screen.findByText(
      "One saved decision; four outside cap.",
      {},
      { timeout: 4000 },
    ),
  ).toBeDefined();
  cleanup();
  render(<App />);
  expect(
    await screen.findByText("One saved decision; four outside cap."),
  ).toBeDefined();
});
