import { expect, test } from "@playwright/test";

import { ensureDocument, signIn } from "./support";

const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";

interface MailpitMessage {
  ID: string;
  Subject: string;
  To: { Address: string }[];
}

test("an approved email is sent, and arrives in Mailpit", async ({ page, request }) => {
  await ensureDocument(request, "information-security-policy-en.pdf", "E2E Approval Policy");
  const subject = `E2E reminder ${String(Date.now())}`;
  await signIn(page, "officer");

  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Draft a reminder email to procurement about the vendor rules");
  await box.press("Enter");

  const card = page.getByRole("region", { name: "Approval: Send an email" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Needs your approval")).toBeVisible();
  await expect(card.getByLabel("To")).toHaveValue("procurement@acme.example");

  // Nothing has been sent yet.
  const before = (await (await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(subject)}`)).json()) as {
    messages: MailpitMessage[];
  };
  expect(before.messages).toHaveLength(0);

  await card.getByLabel("Subject").fill(subject);
  await card.getByRole("button", { name: "Approve with edits" }).click();

  const transcript = page.getByRole("list", { name: "Conversation" });
  await expect(transcript.getByText("Update: The email was sent to procurement@acme.example.")).toBeVisible();
  await expect(card.getByText(/Approved with edits by Compliance Officer/)).toBeVisible();

  await expect
    .poll(async () => {
      const found = (await (await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(subject)}`)).json()) as {
        messages: MailpitMessage[];
      };
      return found.messages.map((m) => [m.Subject, m.To[0]?.Address]);
    })
    .toEqual([[subject, "procurement@acme.example"]]);
});

test("viewers can ask but not approve; approvers see it in their inbox", async ({ browser }) => {
  const viewerPage = await browser.newPage();
  await signIn(viewerPage, "viewer");
  await expect(viewerPage.getByRole("link", { name: "Approvals" })).toHaveCount(0);
  const box = viewerPage.getByRole("textbox", { name: "Message" });
  await box.fill("Please open a ticket to renew the cleaning contract");
  await box.press("Enter");
  const card = viewerPage.getByRole("region", { name: "Approval: Open a ticket" });
  await expect(card.getByText("Waiting for an approver")).toBeVisible();
  await expect(card.getByRole("button", { name: /Approve/ })).toHaveCount(0);
  await viewerPage.close();

  const officerPage = await browser.newPage();
  await signIn(officerPage, "officer");
  await officerPage.getByRole("link", { name: /Approvals/ }).click();
  const cards = officerPage.getByRole("region", { name: "Approval: Open a ticket" });
  await expect(cards.first()).toContainText("Read-only Viewer");
  const waiting = await cards.count();
  await cards.first().getByRole("button", { name: "Reject" }).click();
  await expect(cards).toHaveCount(waiting - 1);
  await officerPage.close();
});
