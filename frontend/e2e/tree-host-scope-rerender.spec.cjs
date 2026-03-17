// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  selectHost,
  setDirectorySearch,
  waitForApiIdle,
  waitForTreeReady,
  escapeRegex,
} = require('./helpers.cjs')

test.describe('tree dup highlight refresh on host add', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('adding a second host re-renders file dup highlighting in expanded C:/tmp', async ({ page }) => {
    await selectHost(page, 'Photoshop-PC')
    await setDirectorySearch(page, 'C:\\tmp')

    const tmpDirRow = page.locator('[data-testid="tree-row"][data-entry-type="dir"][data-path^="__drive__:C"][data-path$="/tmp"]').first()
    await expect(tmpDirRow).toBeVisible({ timeout: 20_000 })
    await tmpDirRow.click()
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    const tmpFileRows = page.locator('[data-testid="tree-row"][data-entry-type="file"][data-path^="__drive__:C/tmp/"]')
    await expect.poll(async () => tmpFileRows.count(), { timeout: 20_000 }).toBeGreaterThan(0)

    const countAmberRows = async () => tmpFileRows.evaluateAll(rows =>
      rows.filter(r => r.className.includes('bg-amber-50')).length
    )

    // Baseline: with only Photoshop-PC selected, /tmp should not show dup-highlighted files.
    await expect.poll(countAmberRows, { timeout: 5_000 }).toBe(0)

    const unraidChip = page.locator('header button').filter({
      hasText: new RegExp(`^${escapeRegex('unraid')}$`, 'i'),
    })
    await expect(unraidChip).toBeVisible({ timeout: 10_000 })
    await unraidChip.click({ modifiers: ['Shift'] })
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    const tmpDirAfter = page.locator('[data-testid="tree-row"][data-entry-type="dir"][data-path^="__drive__:C"][data-path$="/tmp"]').first()
    await expect(tmpDirAfter.locator('[data-testid="dup-badge"]')).toBeVisible({ timeout: 20_000 })

    // Regression guard: expanded file rows should re-render and become highlighted once host scope includes Unraid.
    await expect.poll(countAmberRows, { timeout: 20_000 }).toBeGreaterThan(0)
  })
})
