import { expect, test } from "@playwright/test";

import { ensureDocument, signIn } from "./support";

const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";

test("ask, open a citation and approve an email with the keyboard only", async ({ page, request }) => {
  await ensureDocument(request, "information-security-policy-en.pdf", "E2E Keyboard Policy");
  await signIn(page, "officer");
  const subject = `Keyboard ${String(Date.now())}`;

  // The first Tab reaches the skip link, which jumps past the header and chat list.
  await page.locator("body").focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to the message box" })).toBeFocused();
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "Message" });
  await expect(box).toBeFocused();
  await page.keyboard.type("How long must passwords be?");
  await page.keyboard.press("Enter");

  const chip = page.getByRole("list", { name: "Conversation" }).getByRole("button", { name: /^Source 1: / }).last();
  await expect(chip).toBeVisible();
  await chip.focus();
  await page.keyboard.press("Enter");
  const panel = page.getByRole("complementary");
  await expect(panel.getByRole("button", { name: "Close" })).toBeFocused(); // focus moves into the panel
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);

  // Enter is ignored while an answer is still streaming; wait for it to finish.
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0);
  await box.focus();
  await page.keyboard.type("Draft a reminder email to procurement");
  await page.keyboard.press("Enter");
  const card = page.getByRole("region", { name: "Approval: Send an email" });
  await expect(card).toBeVisible();

  // Reach the subject field and the Approve button with Tab, never the mouse.
  const subjectField = card.getByLabel("Subject");
  await card.getByLabel("To").focus();
  for (let i = 0; i < 5 && !(await subjectField.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(subjectField).toBeFocused();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type(subject);
  const approve = card.getByRole("button", { name: "Approve with edits" });
  for (let i = 0; i < 6 && !(await approve.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(approve).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByText("Update: The email was sent to procurement@acme.example.").last()).toBeVisible();
  await expect
    .poll(async () => {
      const found = (await (await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(subject)}`)).json()) as {
        messages: unknown[];
      };
      return found.messages.length;
    })
    .toBe(1);
});
