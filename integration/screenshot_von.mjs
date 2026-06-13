// Capture dissertation-figure screenshots of Von's web UI showing the
// CiteSeek-ingested knowledge. Run from frontend/ (has playwright):
//   cd frontend && node ../integration/screenshot_von.mjs
import { chromium } from '../frontend/node_modules/playwright/index.mjs';

const BASE = 'http://localhost:5001/von/';
const OUT = new URL('./evidence/', import.meta.url).pathname;
const CLAIM_QUERY = 'Generative adversarial networks train';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

console.log('open', BASE);
await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(5000);
await page.screenshot({ path: `${OUT}von_ui_home.png`, fullPage: false });
console.log('saved von_ui_home.png');

// Global concept search for the CiteSeek-ingested claim
const search = page.locator('#vontologySearchInput');
await search.click();
await search.fill(CLAIM_QUERY);
await page.waitForTimeout(2500); // let the results listbox populate
await page.screenshot({ path: `${OUT}von_ui_search_claim.png` });
console.log('saved von_ui_search_claim.png');

// Open the first search result if present
const results = page.locator('#vontologySearchResults [role="option"], #vontologySearchResults li, #vontologySearchResults div');
const n = await results.count();
console.log('search results elements:', n);
if (n > 0) {
  await results.first().click();
  await page.waitForTimeout(3000);
  // The concept opens as a new tab in the tab bar — activate it
  const conceptTab = page.locator('.tab-button', { hasText: 'Generative adversarial' }).first();
  if (await conceptTab.count()) {
    await conceptTab.click();
    await page.waitForTimeout(4000);
  }
  await page.screenshot({ path: `${OUT}von_ui_claim_concept.png`, fullPage: true });
  console.log('saved von_ui_claim_concept.png');
} else {
  console.log('no clickable results; dumping search region HTML');
  console.log(await page.locator('#globalConceptSearchRegion').innerHTML());
}

await browser.close();
