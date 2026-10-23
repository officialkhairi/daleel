import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ensureDocument, signIn } from "./support";

/** Phase 5 gate: no serious or critical axe violations on any page, in English and Arabic. */
async function scan(page: Page, name: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const blocking = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id} (${v.impact ?? ""}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(blocking, `${name}: ${blocking.join("\n")}`).toEqual([]);
}

async function arabic(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Switch language" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
}

test("sign-in page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await scan(page, "sign-in (en)");
  await page.getByRole("button", { name: "Switch language" }).click();
  await scan(page, "sign-in (ar)");
});

test("chat with an answer, a citation panel and an approval card", async ({ page, request }) => {
  await ensureDocument(request, "information-security-policy-en.pdf", "E2E A11y Policy");
  await signIn(page, "officer");
  await scan(page, "empty chat");

  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("How long must passwords be?");
  await box.press("Enter");
  const chip = page.getByRole("list", { name: "Conversation" }).getByRole("button", { name: /^Source 1: / }).last();
  await chip.click();
  await expect(page.getByRole("complementary").locator("canvas")).toBeVisible();
  await scan(page, "answer + citation panel (en)");
  await page.keyboard.press("Escape");

  await box.fill("Draft a reminder email to procurement");
  await box.press("Enter");
  await expect(page.getByRole("region", { name: "Approval: Send an email" })).toBeVisible();
  await scan(page, "approval card (en)");
  await arabic(page);
  await scan(page, "approval card (ar)");
});

test("documents and approvals pages", async ({ page }) => {
  await signIn(page, "officer");
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("heading", { name: "Add a document" })).toBeVisible();
  await scan(page, "documents (en)");
  await page.getByRole("link", { name: /Approvals/ }).click();
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await scan(page, "approvals (en)");
  await arabic(page);
  await scan(page, "approvals (ar)");
  await page.getByRole("link", { name: "المستندات" }).click();
  await scan(page, "documents (ar)");
});

test("admin console", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page.getByText("Questions asked")).toBeVisible();
  await scan(page, "admin usage (en)");
  await page.getByRole("tab", { name: "Users" }).click();
  await scan(page, "admin users (en)");
  await page.getByRole("tab", { name: "Audit log" }).click();
  await scan(page, "admin audit (en)");
  await arabic(page);
  await page.getByRole("tab", { name: "الاستخدام" }).click();
  await scan(page, "admin usage (ar)");
});
