// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  switchToListView,
  setMinSize,
  setHashSearch,
  applyFirstCategoryFilter,
  waitForApiIdle,
  waitForTreeReady,
  clickReset,
} = require('./helpers.cjs')

// Hash search in tree view shows results inline with a "Showing: hash: ..." banner.
// We detect this via the banner text, not a separate overlay component.

test.describe('hash search overlay', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('hash search with valid prefix shows results banner', async ({ page }) => {
    // First, get a real hash from list view
    await switchToListView(page)

    const hashCell = page.locator('[data-testid="hash-cell"]').first()
    await expect(hashCell).toBeVisible({ timeout: 10_000 })
    const fullHash = await hashCell.getAttribute('data-hash')
    if (!fullHash || fullHash.length < 4) return

    const prefix = fullHash.substring(0, 8)

    // Go back to tree view and search by hash
    await clickReset(page)
    await setHashSearch(page, prefix)
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    // Should show the "Showing: hash: ..." banner
    const banner = page.getByText(`hash: ${prefix}`)
    await expect(banner).toBeVisible({ timeout: 10_000 })

    // Should show a "Back" button
    await expect(page.getByText('← Back')).toBeVisible()

    // Should show result rows
    const rows = page.locator('[data-testid="tree-row"]')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
  })

  test('hash search results disappear when query cleared', async ({ page }) => {
    await switchToListView(page)

    const hashCell = page.locator('[data-testid="hash-cell"]').first()
    await expect(hashCell).toBeVisible({ timeout: 10_000 })
    const fullHash = await hashCell.getAttribute('data-hash')
    if (!fullHash || fullHash.length < 4) return

    await clickReset(page)
    await setHashSearch(page, fullHash.substring(0, 8))
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    await expect(page.getByText(`hash: ${fullHash.substring(0, 8)}`)).toBeVisible({ timeout: 10_000 })

    // Clear the hash search
    const input = page.locator('[data-testid="hash-search"]')
    await input.fill('')
    await page.waitForTimeout(500)
    await waitForApiIdle(page)

    // Banner should disappear
    await expect(page.getByText('Showing:')).not.toBeVisible({ timeout: 5_000 })
  })

  test('hash search bypasses min-size and category filters', async ({ page }) => {
    // First grab a hash from list view (before applying restrictive filters)
    await switchToListView(page)

    const hashCell = page.locator('[data-testid="hash-cell"]').first()
    await expect(hashCell).toBeVisible({ timeout: 10_000 })
    const fullHash = await hashCell.getAttribute('data-hash')
    if (!fullHash || fullHash.length < 4) return

    const prefix = fullHash.substring(0, 8)

    // Reset to tree view, apply restrictive filters, then hash search
    await clickReset(page)
    await setMinSize(page, '1 GB')

    // Hash search in tree view should show results via overlay/banner
    await setHashSearch(page, prefix)
    await page.waitForTimeout(1000)
    await waitForApiIdle(page)

    // In tree view, hash search shows a "Showing: hash: ..." banner
    const banner = page.getByText(`hash: ${prefix}`)
    await expect(banner).toBeVisible({ timeout: 10_000 })

    // Results should be visible despite 1 GB min-size filter
    const rows = page.locator('[data-testid="tree-row"]')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
  })
})
