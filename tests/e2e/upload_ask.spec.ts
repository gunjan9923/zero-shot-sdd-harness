import { test, expect } from '@playwright/test'
import path from 'node:path'

// Resolve the fixture relative to this spec file. Playwright transpiles specs to
// CommonJS, so __dirname is available here.
const FIXTURE = path.join(__dirname, 'fixtures', 'sales.csv')

// The fixture's `amount` column sums to this exact value. The agent runs real
// pandas locally, so the rendered answer must contain this number.
const EXPECTED_TOTAL = '600'

test('upload a CSV, ask a question, and read the real computed answer + code', async ({ page }) => {
  // 1. Navigate to the workspace. A leading-slash path resolves against the
  //    origin, so we use the full app path served by FastAPI's StaticFiles mount.
  await page.goto('/app/')

  // 2. The workspace renders, and the labelled stubs are present + tagged.
  await expect(page.getByText('Analyst Workspace')).toBeVisible()
  // At least one "coming soon" pill proves stubs render as intentional, not bugs.
  const comingSoon = page.getByText('coming soon', { exact: false })
  expect(await comingSoon.count()).toBeGreaterThan(0)
  await expect(comingSoon.first()).toBeVisible()

  // 3. Upload the fixture CSV via the (hidden) file input → real POST /datasets.
  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles(FIXTURE)

  // After upload the UI shows the file name, row count, and column chips.
  await expect(page.getByText('sales.csv')).toBeVisible({ timeout: 30_000 })
  // 5 data rows in the fixture.
  await expect(page.getByText(/5\s*rows/i)).toBeVisible()
  // Column chips for the real schema.
  await expect(page.getByText('amount', { exact: true })).toBeVisible()
  await expect(page.getByText('region', { exact: true })).toBeVisible()
  await expect(page.getByText('order_id', { exact: true })).toBeVisible()

  // 4. Ask a question → real POST /analyses → real Gemini → sandbox execution.
  await page.locator('#question').fill('what is the total of amount?')
  const askButton = page.getByRole('button', { name: 'Ask', exact: true })
  await expect(askButton).toBeEnabled()
  await askButton.click()

  // 5. The answer block renders prose containing the correct total. We assert on
  //    CONTENT (the known sum), not mere visibility. Allow up to 90s for the
  //    real round-trip.
  const answerBlock = page.locator('p.whitespace-pre-wrap').first()
  await expect(answerBlock).toContainText(EXPECTED_TOTAL, { timeout: 90_000 })

  // The collapsible "Show code" panel exists; expanding it reveals pandas that
  // references the `df` DataFrame — proof of real computed code.
  const codePanel = page.locator('details')
  await expect(codePanel).toBeVisible()
  // The <summary> label is "Show code" (preceded by a decorative arrow glyph),
  // so match on the summary element containing that text rather than exact text.
  const summary = codePanel.locator('summary', { hasText: 'Show code' })
  await expect(summary).toBeVisible()
  await summary.click()
  const codeText = codePanel.locator('code')
  await expect(codeText).toBeVisible()
  await expect(codeText).toContainText('df')
})
