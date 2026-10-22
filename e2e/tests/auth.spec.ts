import { expect, test } from "@playwright/test";

import { signIn } from "./support";

test("officer signs in through Keycloak and sees their roles", async ({ page }) => {
  await signIn(page, "officer");
  await page.getByRole("button", { name: "Compliance Officer" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("list", { name: "Roles" })).toHaveText(/Approver\s*Editor/);
  await dialog.getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("the interface switches to Arabic, right to left", async ({ page }) => {
  await signIn(page, "viewer");
  await page.getByRole("button", { name: "Switch language" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("link", { name: "المستندات" })).toBeVisible();
});
