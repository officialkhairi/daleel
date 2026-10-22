// Renders the demo policies to PDF with Chromium (logical-order text, embedded fonts).
// Usage: npx -y playwright@1.64.1 install chromium && node build.mjs   (needs the playwright package)
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";

const dir = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch();
const page = await browser.newPage();
for (const name of ["procurement-policy-ar", "information-security-policy-en"]) {
  await page.goto(`file://${path.join(dir, `${name}.html`)}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({ path: path.join(dir, `${name}.pdf`), format: "A4", preferCSSPageSize: true });
  console.log("wrote", `${name}.pdf`);
}
await browser.close();
