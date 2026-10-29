import { expect, test, type Page } from "@playwright/test";

async function select(page: Page, id: string) {
  await page.getByRole("searchbox", { name: "Search claims" }).fill(id);
  await page
    .getByRole("complementary", { name: "Claims queue" })
    .getByRole("button", { name: new RegExp(`^${id} `) })
    .click();
  await expect(
    page.getByRole("article", { name: `Claim ${id}` }),
  ).toBeVisible();
}

test("approve runs visibly, pays and survives page reload", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await select(page, "E2E-APPROVE");
  await page.getByRole("button", { name: "Run claim" }).click();
  await expect(
    page.getByText("The agent is working on this claim."),
  ).toBeVisible();
  const duplicate = await request.post("/api/claims/E2E-APPROVE/run", {
    data: { thread_id: "duplicate" },
  });
  expect(duplicate.status()).toBe(409);
  await expect(
    page
      .getByText("Read claim and supporting records", { exact: true })
      .first(),
  ).toBeVisible();
  expect((await request.get("/api/health")).status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "Approved", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Simulated payment recorded: $420.00", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Agent run completed.")).toBeVisible();
  await page.getByRole("link", { name: "Policy section 3" }).click();
  await expect(
    page.getByText(/Version 2026\.1, for policies bought/),
  ).toBeVisible();
  await page.reload();
  await select(page, "E2E-APPROVE");
  await expect(
    page.getByText("Simulated payment recorded: $420.00", { exact: true }),
  ).toBeVisible();
});

test("exactly 1000 dollars does not require sign-off", async ({ page }) => {
  await page.goto("/");
  await select(page, "E2E-LIMIT");
  await page.getByRole("button", { name: "Run claim" }).click();
  await expect(
    page.getByText("Simulated payment recorded: $1,000.00", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign off payout" }),
  ).toHaveCount(0);
});

test("over-limit agent payment is blocked until handler sign-off", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await select(page, "E2E-OVER");
  await page.getByRole("button", { name: "Run claim" }).click();
  await expect(page.getByText("Handler sign-off required")).toBeVisible();
  await expect(page.getByText("Agent run completed.")).toBeVisible();
  await expect(
    page.getByText("Request simulated payment: request rejected (409)."),
  ).toBeVisible();
  const rejected = await request.post("/api/claims/E2E-OVER/payment", {
    data: { amount: "1250.00" },
  });
  expect(rejected.status()).toBe(409);
  await expect(
    page.getByRole("button", { name: "Simulate payment" }),
  ).toHaveCount(0);
  await page.getByLabel("Handler", { exact: true }).selectOption("HND-01");
  await page.getByRole("button", { name: "Sign off payout" }).click();
  await expect(page.getByText("Signed off by Dana Whitfield.")).toBeVisible();
  await page.getByRole("button", { name: "Simulate payment" }).click();
  await expect(
    page.getByText("Simulated payment recorded: $1,250.00", { exact: true }),
  ).toBeVisible();
  const repeated = await request.post("/api/claims/E2E-OVER/payment", {
    data: { amount: "1250.00" },
  });
  expect(repeated.status()).toBe(200);
  await page.reload();
  await select(page, "E2E-OVER");
  await expect(
    page.getByText("Simulated payment recorded: $1,250.00", { exact: true }),
  ).toBeVisible();
});

for (const [id, result] of [
  ["E2E-DECLINE", "Declined"],
  ["E2E-REFER", "Referred"],
]) {
  test(`${result} decisions are saved without payment`, async ({ page }) => {
    await page.goto("/");
    await select(page, id);
    await page.getByRole("button", { name: "Run claim" }).click();
    await expect(
      page.getByRole("heading", { name: result, exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Agent run completed.")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Simulate payment" }),
    ).toHaveCount(0);
  });
}

test("two failures leave a claim for a handler", async ({ page }) => {
  await page.goto("/");
  await select(page, "E2E-FAIL");
  await page.getByRole("button", { name: "Run claim" }).click();
  await expect(
    page.getByText(/Agent run failed \(RuntimeError\)/).first(),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Run claim" })).toBeDisabled();
  await expect(
    page.getByText(/Technical failure after 2 attempts/),
  ).toBeVisible();
});

test("mobile desk fits and has no application console errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => {
    errors.push(error.message);
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("article", { name: "Claim CLM-1001" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
