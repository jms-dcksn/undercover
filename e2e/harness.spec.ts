import { expect, test } from "@playwright/test";

test("capped queue persists tasks, retries, read evidence and reconciliation", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on("pageerror", (error) => {
    errors.push(error.message);
  });
  await page.goto("/");
  const before = (await (await request.get("/api/claims")).json()) as {
    claim_id: string;
    state: string;
  }[];
  await expect(page.getByLabel("Claim limit")).toHaveValue("5");
  await page.getByRole("button", { name: "Run queue", exact: true }).click();
  const run = page.getByRole("region", { name: "Queue run" });
  await expect(
    run.getByRole("button", { name: "Queue running" }),
  ).toBeDisabled();
  await expect(run.getByText("Assess claim").first()).toBeVisible();
  await page.reload();
  await expect(
    run.getByRole("button", { name: "Queue running" }),
  ).toBeDisabled();
  await expect(run.getByText("Run completed", { exact: true })).toBeVisible({
    timeout: 75000,
  });
  await expect(
    run.getByText(/5 claims handled; 4 decisions; 2 payments/),
  ).toBeVisible();
  await expect(
    run.getByText(/HARNESS-TWICE: technical failure 2\/2/),
  ).toBeVisible();
  const saved = (await (
    await request.get("/api/agent/runs/latest")
  ).json()) as {
    id: string;
    tasks: { claim_id: string; state: string; admitted: boolean }[];
  };
  expect(saved.tasks.filter((task) => task.admitted)).toHaveLength(5);
  const after = (await (await request.get("/api/claims")).json()) as {
    claim_id: string;
    state: string;
  }[];
  const admitted = new Set(saved.tasks.map((task) => task.claim_id));
  expect(
    after.filter(
      (claim) => !admitted.has(claim.claim_id) && claim.state === "waiting",
    ),
  ).toHaveLength(
    before.filter((claim) => claim.state === "waiting").length - 5,
  );
  await page.getByLabel("Search claims").fill("HARNESS-RETRY");
  await page
    .getByRole("complementary", { name: "Claims queue" })
    .getByRole("button", { name: /^HARNESS-RETRY / })
    .click();
  await expect(
    page.getByText("Claims manual 2026.2 · Section 7"),
  ).toBeVisible();
  await page.getByText("Claims manual 2026.2 · Section 7").click();
  await expect(page.getByText(/Wild animals/)).toBeVisible();
  await expect(
    page.getByText("Simulated payment recorded: $100.00", { exact: true }),
  ).toBeVisible();
  const activity = (await (
    await request.get("/api/claims/HARNESS-RETRY/activity")
  ).json()) as { kind: string }[];
  expect(activity.filter((event) => event.kind === "started")).toHaveLength(2);
  await page.reload();
  await expect(run.getByText(/5 claims handled; 4 decisions/)).toBeVisible();
  expect(errors).toEqual([]);
});
