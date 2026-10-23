import { expect, test } from "@playwright/test";

import { signIn } from "./support";

test("only admins see the admin console", async ({ browser }) => {
  const officer = await browser.newPage();
  await signIn(officer, "officer");
  await expect(officer.getByRole("link", { name: "Admin" })).toHaveCount(0);
  await officer.goto("/admin");
  await expect(officer.getByRole("heading", { name: "Administration" })).toHaveCount(0); // falls back to chat
  await officer.close();

  const admin = await browser.newPage();
  await signIn(admin, "admin");
  await admin.getByRole("link", { name: "Admin" }).click();
  await expect(admin.getByRole("heading", { name: "Administration" })).toBeVisible();
  await expect(admin.getByRole("figure", { name: "Answers per day" })).toBeVisible();
  await admin.getByRole("figure", { name: "Answers per day" }).getByRole("button", { name: "Show as table" }).click();
  await expect(admin.getByRole("table", { name: "Answers per day" })).toBeVisible();
  await admin.getByRole("tab", { name: "Audit log" }).click();
  await expect(admin.getByRole("table", { name: "Audit log" })).toBeVisible();
  await admin.close();
});
