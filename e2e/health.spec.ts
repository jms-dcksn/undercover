import { expect, test } from "@playwright/test";

test("the dashboard shows the seeded claims desk", async ({
  page,
  request,
}) => {
  const health = await request.get("/api/health");
  expect(await health.json()).toEqual({ status: "ok" });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Every claim." }),
  ).toBeVisible();
  await expect(
    page.getByRole("article", { name: "Claim CLM-1001" }),
  ).toBeVisible();
  await page.getByText("Hotel receipt", { exact: false }).first().click();
  await expect(page.getByText(/Hotel Aurelia Fiumicino. Guest/)).toBeVisible();
  await expect(
    page.getByText("Checked bag arrived 30 hours late in Lisbon"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Agent instructions" }).click();
  await expect(
    page.getByRole("heading", { name: "Agent instructions" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      /You are the UnderCover Agent, a travel insurance claims handler/,
    ),
  ).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
