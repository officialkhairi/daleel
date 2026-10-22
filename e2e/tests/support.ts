import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DEMO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/demo");
const ISSUER = process.env.OIDC_ISSUER ?? "http://localhost:8180/realms/daleel";
const SMOKE_CLIENT = process.env.SMOKE_CLIENT_ID ?? "daleel-smoke";
const SMOKE_SECRET = process.env.SMOKE_CLIENT_SECRET ?? "smoke-dev-only";

export type DemoUser = "officer" | "viewer" | "admin";

/** Signs in through the real Keycloak login page (seeded local users, password "demo"). */
export async function signIn(page: Page, user: DemoUser): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.locator("#username").fill(user);
  await page.locator("#password").fill("demo");
  await page.locator("#kc-login").click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** An access token for API setup and cleanup (dev-only password-grant client). */
export async function apiToken(request: APIRequestContext, user: DemoUser): Promise<string> {
  const response = await request.post(`${ISSUER}/protocol/openid-connect/token`, {
    form: { grant_type: "password", client_id: SMOKE_CLIENT, client_secret: SMOKE_SECRET, username: user, password: "demo" },
  });
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { access_token: string }).access_token;
}

interface DocumentRow {
  id: string;
  title: string;
  sha256?: string;
}

/** A demo PDF with a unique trailing comment: uploads are de-duplicated by content hash, and
 * PDF readers ignore anything after %%EOF. */
export function uniquePdf(file: string): Buffer {
  return Buffer.concat([readFileSync(path.join(DEMO, file)), Buffer.from(`\n%e2e ${randomUUID()}\n`)]);
}

/** Removes documents whose title matches, so uploads in a test aren't rejected as duplicates. */
export async function deleteDocuments(request: APIRequestContext, match: RegExp): Promise<void> {
  const token = await apiToken(request, "admin");
  const headers = { Authorization: `Bearer ${token}` };
  const list = (await (await request.get("/api/documents", { headers })).json()) as DocumentRow[];
  for (const doc of list.filter((d) => match.test(d.title))) {
    await request.delete(`/api/documents/${doc.id}`, { headers });
  }
}

/** Uploads a demo PDF through the API and waits until it is ready. */
export async function ensureDocument(
  request: APIRequestContext,
  file: string,
  title: string,
  roles?: string[],
): Promise<string> {
  const token = await apiToken(request, "admin");
  const headers = { Authorization: `Bearer ${token}` };
  await deleteDocuments(request, new RegExp(`^${title}$`));
  const multipart: Record<string, string | { name: string; mimeType: string; buffer: Buffer }> = {
    file: { name: `${title}.pdf`, mimeType: "application/pdf", buffer: uniquePdf(file) },
    title,
  };
  const response = await request.post("/api/documents", {
    headers,
    multipart: roles ? { ...multipart, acl_roles: roles[0] ?? "" } : multipart,
  });
  expect(response.status(), await response.text()).toBe(202);
  const { id } = (await response.json()) as { id: string };
  await expect
    .poll(async () => ((await (await request.get(`/api/documents/${id}`, { headers })).json()) as { status: string }).status, {
      timeout: 60_000,
    })
    .toBe("ready");
  return id;
}
