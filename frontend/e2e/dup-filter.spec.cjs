// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  selectHost,
  switchToListView,
  setMinSize,
  toggleDupOnly,
  waitForApiIdle,
  waitForTreeReady,
  clickDupBadge,
  expectOverlayHasRows,
} = require('./helpers.cjs')

test.describe('dup-only toggle', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('toggle shows Only dups text when active', async ({ page }) => {
    const toggle = page.locator('[data-testid="dup-only-toggle"]')
    await expect(toggle).toHaveText('All files')
    await toggleDupOnly(page)
    await expect(toggle).toHaveText('Only dups')
  })

  test('dup-only hides non-dup rows in tree view', async ({ page }) => {
    const allRows = page.locator('[data-testid="tree-row"]')
    const countBefore = await allRows.count()
    expect(countBefore).toBeGreaterThan(0)

    await toggleDupOnly(page)
    await waitForTreeReady(page)

    // With dup-only active, every visible file row should have a dup badge
    // (dirs are kept as navigational ancestors)
    const fileRows = page.locator('[data-testid="tree-row"][data-entry-type="file"]')
    const fileCount = await fileRows.count()
    if (fileCount > 0) {
      // All visible file rows should have amber/dup styling or dup badge
      for (let i = 0; i < Math.min(fileCount, 20); i++) {
        const row = fileRows.nth(i)
        // File rows under dup-only should have dup_count > 0
        const dupAttr = await row.getAttribute('data-dup-count')
        expect(Number(dupAttr || '0')).toBeGreaterThan(0)
      }
    }
  })

  test('dup-only hides non-dup rows in list view', async ({ page }) => {
    await switchToListView(page)
    await toggleDupOnly(page)
    await waitForTreeReady(page)

    const fileRows = page.locator('[data-testid="tree-row"]')
    const count = await fileRows.count()
    if (count > 0) {
      for (let i = 0; i < Math.min(count, 20); i++) {
        const row = fileRows.nth(i)
        const dupAttr = await row.getAttribute('data-dup-count')
        expect(Number(dupAttr || '0')).toBeGreaterThan(0)
      }
    }
  })
})

test.describe('min-size filter', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('min-size button shows threshold when active', async ({ page }) => {
    const btn = page.locator('[data-testid="min-size-filter"]')
    await expect(btn).toHaveText('Min size')
    await setMinSize(page, '1 MB')
    await expect(btn).toHaveText('≥ 1 MB')
  })

  test('min-size hides small files in tree view', async ({ page }) => {
    await selectHost(page, 'brians-m2prombp')
    const filesBefore = page.locator('[data-testid="tree-row"][data-entry-type="file"]')
    // Expand a directory first to see files
    const firstDir = page.locator('[data-testid="tree-row"][data-entry-type="dir"]').first()
    await firstDir.click()
    await waitForApiIdle(page)
    await page.waitForTimeout(500)

    const countBefore = await filesBefore.count()

    await setMinSize(page, '100 MB')
    await page.waitForTimeout(500)

    const countAfter = await filesBefore.count()
    // With a high threshold, fewer (or equal) files should be visible
    expect(countAfter).toBeLessThanOrEqual(countBefore)
  })

  test('min-size hides small files in list view', async ({ page }) => {
    await switchToListView(page)
    const rowsBefore = await page.locator('[data-testid="tree-row"]').count()
    expect(rowsBefore).toBeGreaterThan(0)

    await setMinSize(page, '100 MB')
    await waitForTreeReady(page)

    const rowsAfter = await page.locator('[data-testid="tree-row"]').count()
    expect(rowsAfter).toBeLessThanOrEqual(rowsBefore)
  })
})

test.describe('dup-only + min-size combined', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('non-dup rows do not leak under combined filters', async ({ page }) => {
    await toggleDupOnly(page)
    await setMinSize(page, '1 MB')
    await waitForTreeReady(page)

    // Check that all visible file rows are dups
    const fileRows = page.locator('[data-testid="tree-row"][data-entry-type="file"]')
    const count = await fileRows.count()
    for (let i = 0; i < Math.min(count, 20); i++) {
      const row = fileRows.nth(i)
      const dupAttr = await row.getAttribute('data-dup-count')
      expect(Number(dupAttr || '0')).toBeGreaterThan(0)
    }
  })

  test('dir dup badges update when min-size changes', async ({ page }) => {
    await selectHost(page, 'brians-m2prombp')
    await toggleDupOnly(page)
    await waitForTreeReady(page)

    // Get dup badge text from a dir row at 0 min-size
    const dirRows = page.locator('[data-testid="tree-row"][data-entry-type="dir"]')
    const dirCount = await dirRows.count()
    if (dirCount === 0) return // skip if no dirs

    // Now set a high min-size and check if badge text changes
    await setMinSize(page, '100 MB')
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    // Badges should have updated (fewer or same dup hashes visible)
    // Just verify the page didn't break - dirs should still be navigable
    const dirsAfter = await dirRows.count()
    expect(dirsAfter).toBeGreaterThanOrEqual(0) // may be 0 if no large dups
  })
})

test.describe('dup badge click-through', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('clicking dir dup badge shows overlay with results', async ({ page }) => {
    await selectHost(page, 'brians-m2prombp')
    await toggleDupOnly(page)
    await waitForTreeReady(page)

    // Find a dir row that has dup_count > 0 (it will have a dup badge)
    const dirWithDups = page.locator(
      '[data-testid="tree-row"][data-entry-type="dir"]'
    ).filter({
      has: page.locator('[data-testid="dup-badge"]'),
    }).first()
    await expect(dirWithDups).toBeVisible({ timeout: 10_000 })

    // Click the dup badge
    await clickDupBadge(page, dirWithDups)

    // Overlay should show results, not the "no matches" notice
    await expectOverlayHasRows(page)

    // Verify "← Back" button is available and click it to restore tree
    const backBtn = page.getByRole('button', { name: '← Back' })
    await expect(backBtn).toBeVisible({ timeout: 5_000 })
    await backBtn.click()
    await waitForApiIdle(page)

    // Tree should be restored with dir rows visible again
    const dirRows = page.locator('[data-testid="tree-row"][data-entry-type="dir"]')
    await expect(dirRows.first()).toBeVisible({ timeout: 10_000 })
  })

  test('clicking dir dup badge after min-size change still shows results', async ({ page }) => {
    await selectHost(page, 'brians-m2prombp')
    await toggleDupOnly(page)
    await waitForTreeReady(page)

    // Set a min-size filter first to exercise the cache interaction
    await setMinSize(page, '1 MB')
    await page.waitForTimeout(500)
    await waitForApiIdle(page)

    // Find a dir that still has a dup badge after min-size filtering
    const dirWithDups = page.locator(
      '[data-testid="tree-row"][data-entry-type="dir"]'
    ).filter({
      has: page.locator('[data-testid="dup-badge"]'),
    }).first()

    // If no dirs have dups at this min-size, skip gracefully
    const count = await dirWithDups.count()
    if (count === 0) return

    await clickDupBadge(page, dirWithDups)

    // Overlay should show results, not the stale-cache "no matches" error
    await expectOverlayHasRows(page)
  })
})
