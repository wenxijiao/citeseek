// UI smoke test: hero page -> submit claim -> workbench panes -> screenshots.
import { chromium } from 'playwright'

const BASE = process.env.BASE_URL ?? 'http://localhost:8000'
const OUT = new URL('../screenshots/', import.meta.url).pathname

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})

await page.goto(BASE)
// Fresh state: forget any remembered session so the hero shows.
await page.evaluate(() => localStorage.clear())
await page.reload()
await page.waitForSelector('text=Credit where credit is due', { timeout: 10000 })
await page.screenshot({ path: OUT + '1-hero.png' })

await page.fill('textarea', 'GANs train a generator and a discriminator through an adversarial process')
await page.click('button[title="Find supporting papers"]')
await page.waitForSelector('text=Supporting evidence', { timeout: 15000 })
await page.screenshot({ path: OUT + '2-pipeline.png' })

// Wait for the pipeline to finish (candidates rendered)
await page.waitForSelector('article', { timeout: 240000 })
await page.waitForTimeout(800)
await page.screenshot({ path: OUT + '3-candidates.png' })

// Open the first open-access candidate in the reader, if any
const readBtn = page.locator('button:has-text("Read here")').first()
if (await readBtn.count()) {
  await readBtn.click()
  await page.waitForSelector('.reader-prose [data-p="0"]', { timeout: 120000 })
  await page.waitForTimeout(500)
  await page.screenshot({ path: OUT + '4-reader.png' })

  // Select a sentence inside the first paragraph to trigger the popover
  await page.evaluate(() => {
    const p = document.querySelector('.reader-prose [data-p="2"], .reader-prose [data-p="0"]')
    const range = document.createRange()
    const textNode = p.firstChild
    range.setStart(textNode, 0)
    range.setEnd(textNode, Math.min(80, textNode.textContent.length))
    const sel = window.getSelection()
    sel.removeAllRanges()
    sel.addRange(range)
  })
  await page.mouse.move(400, 300)
  // mouseup on the reader to fire the handler
  await page.locator('.reader-prose').dispatchEvent('mouseup')
  await page.waitForSelector('text=Find evidence', { timeout: 5000 })
  await page.screenshot({ path: OUT + '5-selection.png' })
}

// Dark mode
await page.keyboard.press('Escape')
await page.click('button[title="Toggle theme"]')
await page.waitForTimeout(300)
await page.screenshot({ path: OUT + '6-dark.png' })

console.log('errors:', errors.length ? errors : 'none')
await browser.close()
