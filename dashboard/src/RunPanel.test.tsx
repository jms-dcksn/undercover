import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RunPanel } from "./RunPanel";
import type { QueueRun, TaskState } from "./types";

const run: QueueRun = {
  id: "parent",
  state: "completed",
  mode: "queue",
  claim_limit: 5,
  snapshot: [],
  tasks: [],
  summary: "Saved final summary",
  error: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("validates caps and submits exactly one capped parent", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
  const changed = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<RunPanel run={null} error={null} onChange={changed} />);
  expect(screen.getByLabelText("Claim limit")).toHaveProperty("value", "5");
  fireEvent.change(screen.getByLabelText("Claim limit"), {
    target: { value: "0" },
  });
  expect(screen.getByRole("button", { name: "Run queue" })).toHaveProperty(
    "disabled",
    true,
  );
  fireEvent.submit(screen.getByRole("form", { name: "Queue scope" }));
  expect(fetcher).not.toHaveBeenCalled();
  expect(
    screen.getByText("Enter a positive whole-number claim limit."),
  ).toBeDefined();
  fireEvent.change(screen.getByLabelText("Claim limit"), {
    target: { value: "5" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Run queue" }));
  expect(screen.getByRole("button", { name: "Starting…" })).toHaveProperty(
    "disabled",
    true,
  );
  await waitFor(() => {
    expect(changed).toHaveBeenCalledOnce();
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/api/agent/runs",
    expect.objectContaining({
      body: expect.stringContaining('"claim_limit":5') as string,
    }),
  );
});

it("starts an uncapped queue and displays API failures", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "Another run is active." }), {
      status: 409,
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<RunPanel run={run} error={null} onChange={vi.fn()} />);
  fireEvent.click(screen.getByLabelText("All waiting claims"));
  expect(screen.getByLabelText("Claim limit")).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByRole("button", { name: "Run queue" }));
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Another run is active.",
  );
  expect(fetcher).toHaveBeenCalledWith(
    "/api/agent/runs",
    expect.objectContaining({
      body: expect.stringContaining('"claim_limit":null') as string,
    }),
  );
});

it("renders every persisted task state and locks active controls", () => {
  const states: TaskState[] = [
    "todo",
    "in_progress",
    "done",
    "left_for_handler",
  ];
  const tasks = states.map((state, position) => ({
    claim_id: `CLAIM-${String(position)}`,
    state,
    description: "Assess claim",
    position,
    admitted: state !== "todo",
    result: state === "left_for_handler" ? "technical failure 2/2" : null,
  }));
  render(
    <RunPanel
      run={{ ...run, state: "running", tasks, claim_limit: null }}
      error={null}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText("To do")).toBeDefined();
  expect(screen.getByText("In progress")).toBeDefined();
  expect(screen.getByText("Done")).toBeDefined();
  expect(screen.getByText("Left for handler")).toBeDefined();
  expect(screen.getByText("technical failure 2/2")).toBeDefined();
  expect(screen.getByRole("button", { name: "Queue running" })).toHaveProperty(
    "disabled",
    true,
  );
  expect(screen.getByLabelText("All waiting claims")).toHaveProperty(
    "disabled",
    true,
  );
});

it("retains terminal errors and empty run summaries", () => {
  render(
    <RunPanel
      run={{ ...run, state: "failed", error: "Coordinator stopped." }}
      error="Connection unavailable"
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText("Run failed")).toBeDefined();
  expect(screen.getByText("No tasks in this run.")).toBeDefined();
  expect(screen.getAllByRole("alert")).toHaveLength(2);
  expect(screen.getByText("Saved final summary")).toBeDefined();
});
