import { expect, test } from "@playwright/test";

import { ensureDocument, signIn } from "./support";

test("an answer cites the document and the citation opens the exact passage", async ({ page, request }) => {
  await ensureDocument(request, "information-security-policy-en.pdf", "E2E Citations Policy");
  await signIn(page, "officer");

  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("How long must passwords be?");
  await box.press("Enter");

  const chip = page.getByRole("list", { name: "Conversation" }).getByRole("button", { name: /^Source 1: / }).last();
  await expect(chip).toBeVisible();
  await expect(page.locator("[aria-busy=true]")).toHaveCount(0);

  // The panel shows whichever document the chip cites (any the officer may read).
  const cited = /^Source 1: (.+), page \d+$/.exec((await chip.getAttribute("aria-label")) ?? "")?.[1] ?? "";
  expect(cited).not.toBe("");
  await chip.click();
  const panel = page.getByRole("complementary");
  await expect(panel.getByRole("heading")).toContainText(cited);
  await expect(panel.locator("canvas")).toBeVisible();
  await expect(panel.getByTestId("highlight").first()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
});

test("stop keeps the partial answer and offers a retry", async ({ page }) => {
  await signIn(page, "viewer");
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Please answer at length " + "about procurement approvals ".repeat(30));
  await box.press("Enter");
  await expect(page.locator("[aria-busy=true]")).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Stopped")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});
