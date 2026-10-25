// Records a captioned, step-by-step walkthrough as a WebM video.
// Needs a fresh stack with a real model (the demo uploads the documents itself):
//   corepack pnpm --filter @daleel/e2e exec node scripts/record-video.mjs <out-dir>
import { mkdirSync, renameSync } from "node:fs";
import path from "node:path";

import { chromium } from "@playwright/test";

const BASE = process.env.BASE_URL ?? "http://localhost:5173";
const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";
const TICKETS = process.env.TICKETING_URL ?? "http://localhost:8090";
const DEMO = path.resolve(import.meta.dirname, "../../docs/demo");
const out = process.argv[2];
if (!out) throw new Error("usage: record-video.mjs <out-dir>");
mkdirSync(out, { recursive: true });

const size = { width: 1280, height: 800 };
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: size, recordVideo: { dir: out, size } });

// A visible cursor (headless video has none) and the caption box, on every page.
await context.addInitScript(() => {
  const install = () => {
    if (document.getElementById("demo-cursor")) return;
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    Object.assign(cursor.style, {
      position: "fixed", zIndex: 2147483647, width: "22px", height: "22px", borderRadius: "50%",
      background: "rgba(232, 160, 0, .45)", border: "2px solid #b77a00", pointerEvents: "none",
      transform: "translate(-50%, -50%)", left: "-40px", top: "-40px", transition: "width .12s, height .12s",
    });
    document.documentElement.append(cursor);
    addEventListener("mousemove", (e) => { cursor.style.left = `${e.clientX}px`; cursor.style.top = `${e.clientY}px`; }, true);
    addEventListener("mousedown", () => { cursor.style.width = cursor.style.height = "14px"; }, true);
    addEventListener("mouseup", () => { cursor.style.width = cursor.style.height = "22px"; }, true);
    const box = document.createElement("div");
    box.id = "demo-caption";
    Object.assign(box.style, {
      position: "fixed", zIndex: 2147483646, insetInlineStart: "50%", top: "8px", transform: "translateX(-50%)",
      maxWidth: "560px", padding: "8px 16px", borderRadius: "10px", background: "rgba(16, 32, 36, .92)",
      color: "#fff", font: "500 14px/1.35 system-ui, sans-serif", boxShadow: "0 6px 20px rgba(0,0,0,.25)",
      pointerEvents: "none", direction: "ltr", textAlign: "left",
    });
    const text = sessionStorage.getItem("demo-caption");
    box.innerHTML = text ?? "";
    box.style.display = text ? "block" : "none";
    document.documentElement.append(box);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", install);
  else install();
});

const page = await context.newPage();
const pause = (ms) => page.waitForTimeout(ms);
const total = 10;

/** Shows "Step n of 10 · title" with a one-line explanation; it survives navigations. */
let caption = "";
async function showCaption() {
  await page.evaluate((h) => {
    sessionStorage.setItem("demo-caption", h);
    const box = document.getElementById("demo-caption");
    if (box) { box.innerHTML = h; box.style.display = h ? "block" : "none"; }
  }, caption);
}

async function step(n, title, detail) {
  const html = `<div style="opacity:.7;font-size:12px">Step ${n} of ${total}</div><div style="font-weight:650;font-size:16px">${title}</div><div style="opacity:.85">${detail}</div>`;
  caption = html;
  await showCaption();
  await pause(2200);
}

/** Moves the visible cursor to an element, then clicks it. */
async function click(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
  await pause(250);
  await locator.click();
}

async function hover(locator) {
  const box = await locator.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
}

async function ask(text) {
  const composer = page.locator("#composer");
  await click(composer);
  await page.keyboard.type(text, { delay: 30 });
  await pause(400);
  await page.keyboard.press("Enter");
}

const answered = () => page.getByRole("button", { name: "Stop" }).waitFor({ state: "detached", timeout: 180_000 });

async function signIn(user) {
  await click(page.getByRole("button", { name: "Sign in" }));
  await page.locator("#username").waitFor();
  await showCaption(); // Keycloak is another origin
  await pause(1200);
  await click(page.locator("#username"));
  await page.keyboard.type(user, { delay: 60 });
  await click(page.locator("#password"));
  await page.keyboard.type("demo", { delay: 60 });
  await pause(400);
  await click(page.locator("#kc-login"));
  await page.getByRole("button", { name: "Sign out" }).waitFor();
}

// 1 ─ Sign in
await page.goto(BASE);
await step(1, "Sign in with single sign-on", "Keycloak handles login (OIDC + PKCE). The API checks every token and role itself.");
await signIn("officer");
await pause(1500);

// 2 ─ Upload
await click(page.getByRole("link", { name: "Documents" }));
await step(2, "Upload enterprise documents", "An English security policy and an Arabic procurement policy. The worker parses, chunks and indexes them; progress arrives live.");
for (const [file, title] of [
  ["information-security-policy-en.pdf", "Information Security Policy"],
  ["procurement-policy-ar.pdf", "سياسة المشتريات والتعاقد مع الموردين"],
]) {
  await page.getByLabel(/Drop a file here/).setInputFiles(path.join(DEMO, file));
  await click(page.getByLabel("Title (optional)"));
  await page.keyboard.type(title, { delay: 25 });
  await click(page.getByRole("button", { name: "Upload" }));
  await page.getByRole("row", { name: new RegExp(title) }).getByText("Ready").waitFor({ timeout: 120_000 });
  await pause(1200);
}
await pause(1500);

// 3 ─ Grounded answer
await click(page.getByRole("link", { name: "Chat" }));
await step(3, "Ask a question, get a cited answer", "The answer streams in and cites the exact passages it used. Citations to anything not retrieved are removed.");
await ask("How quickly must a security incident be reported, and to whom?");
await answered();
await pause(1500);
const chip = page.getByRole("list", { name: "Conversation" }).getByRole("button", { name: /^Source \d+: / }).first();
await hover(chip);
await pause(2500);

// 4 ─ Open the source
await step(4, "Open the exact passage", "Clicking a citation opens the PDF at that page with the passage highlighted.");
await click(chip);
await page.getByRole("complementary").locator("canvas").first().waitFor();
await pause(4000);
await click(page.getByRole("complementary").getByRole("button", { name: "Close" }));
await pause(800);

// 5 ─ Arabic UI
await step(5, "Fully bilingual: Arabic, right to left", "Every string is translated and the layout mirrors with CSS logical properties.");
await click(page.locator("header button").filter({ hasText: "العربية" }));
await pause(3500);
await click(page.locator("header button").filter({ hasText: "English" }));
await pause(1200);

// 6 ─ Human-approved email
await click(page.getByRole("button", { name: "New chat" }));
await step(6, "The agent proposes an action, a person approves it", "Side effects (email, tickets) always pause for an approver, who can edit the draft first.");
await ask("Email security-team@acme.example a reminder that incidents must be reported within 2 hours.");
const emailCard = page.getByRole("region", { name: "Approval: Send an email" });
await emailCard.waitFor({ timeout: 180_000 });
await answered();
await emailCard.scrollIntoViewIfNeeded();
await pause(2500);
await click(emailCard.getByLabel("Subject"));
await page.keyboard.press("ControlOrMeta+a");
await page.keyboard.type("Reminder: report incidents within 2 hours", { delay: 30 });
await pause(800);
await click(emailCard.getByRole("button", { name: /^Approve/ }).first());
await emailCard.getByText(/Approved with edits by/).waitFor({ timeout: 60_000 });
await answered();
await pause(3000);

// 7 ─ Approvals inbox
await step(7, "Approvals inbox", "Requests can also be approved from a shared inbox. Each approval runs exactly once and is audited.");
await ask("Create a high priority ticket to review which vendors can access Confidential data.");
await page.getByRole("region", { name: "Approval: Open a ticket" }).waitFor({ timeout: 180_000 });
await answered();
await pause(1500);
await click(page.getByRole("link", { name: /Approvals/ }));
const ticketCard = page.getByRole("region", { name: "Approval: Open a ticket" }).first();
await ticketCard.waitFor();
await pause(2500);
await click(ticketCard.getByRole("button", { name: /^Approve/ }).first());
// Decided requests leave the inbox; the chat shows the outcome.
await ticketCard.waitFor({ state: "detached", timeout: 60_000 });
await pause(1500);
await click(page.getByRole("link", { name: "Chat" }));
// The ticket was asked in the same chat as the email.
await click(page.getByText(/^Email security-team/).first());
await page.getByText(/Created ticket/).last().waitFor({ timeout: 60_000 });
await answered();
await pause(3500);

// 8 ─ The email arrived
await page.goto(MAILPIT);
await showCaption();
await step(8, "The approved email was sent", "Locally it lands in Mailpit, with the subject the approver wrote.");
await click(page.getByText("Reminder: report incidents within 2 hours").first());
await pause(3500);

// 9 ─ The ticket exists
await page.goto(TICKETS);
await step(9, "The approved ticket was opened", "A stand-in for Jira or ServiceNow received it.");
await pause(3000);

// 10 ─ Admin
await page.goto(BASE);
await click(page.getByRole("button", { name: "Sign out" }));
await page.getByRole("button", { name: "Sign in" }).waitFor();
await step(10, "Administration and audit", "Admins see usage (answers, time to first word, tokens, cost), users and roles, and an append-only audit log.");
await signIn("admin");
await click(page.getByRole("link", { name: "Admin" }));
await pause(4000);
await page.mouse.wheel(0, 500);
await pause(2500);
await click(page.getByRole("tab", { name: "Audit log" }));
await pause(4500);
await page.evaluate(() => {
  const h = '<div style="font-weight:650;font-size:16px">Daleel · دليل</div><div style="opacity:.85">Bilingual document copilot: cited answers, human-approved actions.</div>';
  sessionStorage.setItem("demo-caption", h);
  document.getElementById("demo-caption").innerHTML = h;
});
await pause(3000);

const video = page.video();
await context.close();
await browser.close();
const file = path.join(out, "daleel-demo.webm");
renameSync(await video.path(), file);
console.log(file);
