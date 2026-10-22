import { expect, test } from "@playwright/test";

import { deleteDocuments, ensureDocument, signIn, uniquePdf } from "./support";

test("an editor uploads a PDF and watches it become ready", async ({ page, request }) => {
  await deleteDocuments(request, /^E2E Security Policy$/);
  await signIn(page, "officer");
  await page.getByRole("link", { name: "Documents" }).click();

  await page.getByLabel(/Drop a file here/).setInputFiles({
    name: "information-security-policy-en.pdf",
    mimeType: "application/pdf",
    buffer: uniquePdf("information-security-policy-en.pdf"),
  });
  await page.getByLabel("Title (optional)").fill("E2E Security Policy");
  await page.getByRole("button", { name: "Upload" }).click();

  const row = page.getByRole("row", { name: /E2E Security Policy/ });
  await expect(row).toBeVisible();
  await expect(row.getByText("Ready")).toBeVisible({ timeout: 60_000 }); // pushed over the WebSocket
  await expect(row).toContainText("1 page");
});

test("viewers can't upload and don't see restricted documents", async ({ page, request }) => {
  await ensureDocument(request, "information-security-policy-en.pdf", "E2E Board Memo", ["approver"]);
  await signIn(page, "viewer");
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Add a document" })).toHaveCount(0);
  await expect(page.getByRole("row", { name: /E2E Board Memo/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Delete/ })).toHaveCount(0);
});
