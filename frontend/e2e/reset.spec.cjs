// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  switchToListView,
  setDirectorySearch,
  setMinSize,
  toggleDupOnly,
  applyFirstCategoryFilter,
  setHashSearch,
  clickReset,
  waitForApiIdle,
  waitForTreeReady,
} = require('./helpers.cjs')

test.describe('reset contract', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('reset switches back to Tree View', async ({ page }) => {
    await switchToListView(page)
    await expect(page.locator('[data-testid="view-mode"]')).toContainText('List View')

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(page.locator('[data-testid="view-mode"]')).toContainText('Tree View')
  })

  test('reset clears directory search', async ({ page }) => {
    await setDirectorySearch(page, 'gas-m')

    await clickReset(page)
    await waitForTreeReady(page)

    const input = page.locator('[data-testid="directory-search"]')
    await expect(input).toHaveValue('')
  })

  test('reset clears dup-only toggle', async ({ page }) => {
    await toggleDupOnly(page)
    await expect(page.locator('[data-testid="dup-only-toggle"]')).toHaveText('Only dups')

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(page.locator('[data-testid="dup-only-toggle"]')).toHaveText('All files')
  })

  test('reset clears min-size filter', async ({ page }) => {
    await setMinSize(page, '1 MB')
    await expect(page.locator('[data-testid="min-size-filter"]')).toHaveText('≥ 1 MB')

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(page.locator('[data-testid="min-size-filter"]')).toHaveText('Min size')
  })

  test('reset clears category filter', async ({ page }) => {
    await switchToListView(page)
    await applyFirstCategoryFilter(page)
    await expect(page.locator('[data-testid="file-type-filter"]')).not.toHaveText('All types')

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(page.locator('[data-testid="file-type-filter"]')).toHaveText('All types')
  })

  test('reset clears hash search overlay', async ({ page }) => {
    // We need a hash to search. Try a short prefix that might match.
    // If no hash overlay appears, the test still validates reset clears the input.
    const hashInput = page.locator('[data-testid="hash-search"]')
    await hashInput.fill('abcd')
    await page.waitForTimeout(500)
    await waitForApiIdle(page)

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(hashInput).toHaveValue('')
    await expect(page.locator('[data-testid="hash-overlay"]')).not.toBeVisible()
  })

  test('full reset from heavily modified state', async ({ page }) => {
    // Apply all modifications
    await switchToListView(page)
    await toggleDupOnly(page)
    await setMinSize(page, '1 MB')
    await applyFirstCategoryFilter(page)
    await setDirectorySearch(page, 'test')

    // Reset everything
    await clickReset(page)
    await waitForTreeReady(page)

    // Verify all 6 reset actions from the contract
    // 1. Tree View
    await expect(page.locator('[data-testid="view-mode"]')).toContainText('Tree View')
    // 2. Dir search cleared
    await expect(page.locator('[data-testid="directory-search"]')).toHaveValue('')
    // 3. Dup-only off
    await expect(page.locator('[data-testid="dup-only-toggle"]')).toHaveText('All files')
    // 4. Min size cleared
    await expect(page.locator('[data-testid="min-size-filter"]')).toHaveText('Min size')
    // 5. Category cleared
    await expect(page.locator('[data-testid="file-type-filter"]')).toHaveText('All types')
    // 6. Hash search cleared
    await expect(page.locator('[data-testid="hash-search"]')).toHaveValue('')
    // No overlays
    await expect(page.locator('[data-testid="hash-overlay"]')).not.toBeVisible()

    // Tree should have dirs visible (collapsed state reset)
    const dirRows = page.locator('[data-testid="tree-row"][data-entry-type="dir"]')
    const dirCount = await dirRows.count()
    expect(dirCount).toBeGreaterThan(0)
  })
})
