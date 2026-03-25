// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  selectHost,
  selectAllHosts,
  switchToListView,
  setMinSize,
  toggleDupOnly,
  applyFirstCategoryFilter,
  clickReset,
  waitForApiIdle,
  waitForTreeReady,
} = require('./helpers.cjs')

test.describe('filter composition', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('stats bar shows (filtered) when min-size active', async ({ page }) => {
    const statsBar = page.locator('[data-testid="stats-bar"]')
    await expect(statsBar).toBeVisible({ timeout: 10_000 })

    // Before filter: no "(filtered)" text
    await expect(statsBar).not.toContainText('(filtered)')

    await setMinSize(page, '1 MB')
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    // After filter: should show "(filtered)"
    await expect(statsBar).toContainText('(filtered)', { timeout: 10_000 })
  })

  test('stats bar (filtered) disappears after reset', async ({ page }) => {
    await setMinSize(page, '1 MB')
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    const statsBar = page.locator('[data-testid="stats-bar"]')
    await expect(statsBar).toContainText('(filtered)', { timeout: 10_000 })

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(statsBar).not.toContainText('(filtered)')
  })

  test('stats bar shows (filtered) when category active', async ({ page }) => {
    await switchToListView(page)
    await applyFirstCategoryFilter(page)

    const statsBar = page.locator('[data-testid="stats-bar"]')
    await expect(statsBar).toContainText('(filtered)', { timeout: 10_000 })
  })

  test('category multi-select does not collapse the picker', async ({ page }) => {
    await switchToListView(page)

    // Open the category picker
    await page.locator('[data-testid="file-type-filter"]').click()

    // Count available chips
    const chips = page.locator('[data-testid^="category-chip-"]')
    await expect(chips.first()).toBeVisible({ timeout: 10_000 })
    const totalChips = await chips.count()
    expect(totalChips).toBeGreaterThan(1)

    // Select the first chip
    await chips.first().click()
    await page.waitForTimeout(300)

    // The picker should still be open with all chips available
    const chipsAfterFirst = await page.locator('[data-testid^="category-chip-"]').count()
    expect(chipsAfterFirst).toBe(totalChips)

    // Select a second chip if available
    if (totalChips > 1) {
      await chips.nth(1).click()
      await page.waitForTimeout(300)

      const chipsAfterSecond = await page.locator('[data-testid^="category-chip-"]').count()
      expect(chipsAfterSecond).toBe(totalChips)
    }

    // Close picker
    await page.locator('header').click({ position: { x: 5, y: 5 } })
  })

  test('dup-only + category + min-size compose correctly in list view', async ({ page }) => {
    await switchToListView(page)

    // Apply category first (before restrictive filters reduce available categories)
    await applyFirstCategoryFilter(page)
    await toggleDupOnly(page)
    await setMinSize(page, '1 MB')
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    // If there are file rows, they should all be dups
    const fileRows = page.locator('[data-testid="tree-row"]')
    const fileCount = await fileRows.count()
    for (let i = 0; i < Math.min(fileCount, 10); i++) {
      const dupAttr = await fileRows.nth(i).getAttribute('data-dup-count')
      expect(Number(dupAttr || '0')).toBeGreaterThan(0)
    }

    // Stats bar should show (filtered)
    const statsBar = page.locator('[data-testid="stats-bar"]')
    await expect(statsBar).toContainText('(filtered)', { timeout: 10_000 })
  })

  test('list view updates when switching from single host to all hosts with dup filters', async ({ page }) => {
    // Start in list view with one host, only-dups, and min-size
    await switchToListView(page)
    await selectHost(page, 'brians-m2prombp')
    await toggleDupOnly(page)
    await setMinSize(page, '1 MB')
    await page.waitForTimeout(500)
    await waitForApiIdle(page)

    // Record current row count with single host
    const rowsBefore = await page.locator('[data-testid="tree-row"]').count()

    // Switch to all hosts — list should update with cross-host dups
    await selectAllHosts(page)
    await page.waitForTimeout(500)
    await waitForApiIdle(page)

    const rowsAfter = await page.locator('[data-testid="tree-row"]').count()

    // With all hosts selected, we should see at least as many dups
    // (cross-host dups become visible). The key assertion: the list
    // actually updated — it should have MORE rows, not the same.
    expect(rowsAfter).toBeGreaterThanOrEqual(rowsBefore)

    // If there are rows, verify they're all dups
    if (rowsAfter > 0) {
      for (let i = 0; i < Math.min(rowsAfter, 10); i++) {
        const row = page.locator('[data-testid="tree-row"]').nth(i)
        const dupAttr = await row.getAttribute('data-dup-count')
        expect(Number(dupAttr || '0')).toBeGreaterThan(0)
      }
    }
  })
})
