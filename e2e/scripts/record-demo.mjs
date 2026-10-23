// Records the README demo as PNG frames (docs/demo/make-gif.py turns them into a GIF).
// Needs a running stack with a real model and the demo documents uploaded:
//   corepack pnpm --filter @daleel/e2e exec node scripts/record-demo.mjs <frames-dir>
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { chromium } from "@playwright/test";

const BASE = process.env.BASE_URL ?? "http://localhost:5173";
const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";
const out = process.argv[2];
if (!out) throw new Error("usage: record-demo.mjs <frames-dir>");
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 760 } });

const frames = [];
let recording = true;
const capture = (async () => {
  while (recording) {
    frames.push({ at: Date.now(), png: await page.screenshot() });
    await new Promise((r) => setTimeout(r, 200));
  }
})();
const pause = (ms) => page.waitForTimeout(ms);
const type = async (text) => {
  await page.getByRole("textbox", { name: "Message" }).click();
  await page.keyboard.type(text, { delay: 28 });
  await pause(300);
  await page.keyboard.press("Enter");
};
const answerDone = () => page.getByRole("button", { name: "Stop" }).waitFor({ state: "detached", timeout: 120_000 });

// Sign in through Keycloak.
await page.goto(BASE);
await pause(800);
await page.getByRole("button", { name: "Sign in" }).click();
await page.locator("#username").pressSequentially("officer", { delay: 40 });
await page.locator("#password").fill("demo");
await page.locator("#kc-login").click();
await page.getByRole("button", { name: "Sign out" }).waitFor();
await pause(800);

// A grounded, cited answer; open the cited passage in the PDF.
await type("How quickly must a security incident be reported, and to whom?");
await answerDone();
await pause(1200);
const chip = page.getByRole("list", { name: "Conversation" }).getByRole("button", { name: /^Source \d+: / }).first();
await chip.hover();
await pause(1200);
await chip.click();
await page.getByRole("complementary").locator("canvas").first().waitFor();
await pause(2500);
await page.keyboard.press("Escape");
await pause(600);

// An action that needs a person: the agent drafts an email and waits for approval.
await type("Email security-team@acme.example a reminder that incidents must be reported within 2 hours.");
const card = page.getByRole("region", { name: "Approval: Send an email" });
await card.waitFor({ timeout: 120_000 });
await answerDone();
await card.scrollIntoViewIfNeeded();
await pause(1800);
const subject = card.getByLabel("Subject");
await subject.click();
await page.keyboard.press("ControlOrMeta+a");
await page.keyboard.type("Reminder: report incidents within 2 hours", { delay: 25 });
await pause(800);
await card.getByRole("button", { name: /^Approve/ }).first().click();
await page.getByText(/sent/i).last().waitFor({ timeout: 120_000 });
await answerDone();
await pause(2000);

// The approved email arrived.
await page.goto(MAILPIT);
await page.getByText("Reminder: report incidents within 2 hours").first().click();
await pause(2500);

recording = false;
await capture;
await browser.close();

const timings = frames.map((f, i) => ({ file: `${String(i).padStart(4, "0")}.png`, ms: (frames[i + 1]?.at ?? f.at + 1500) - f.at }));
frames.forEach((f, i) => writeFileSync(path.join(out, timings[i].file), f.png));
writeFileSync(path.join(out, "timings.json"), JSON.stringify(timings));
console.log(`${frames.length} frames in ${out}`);
