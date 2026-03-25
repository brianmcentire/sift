// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  selectHost,
  switchToListView,
  setDirectorySearch,
  applyFirstCategoryFilter,
  waitForApiIdle,
} = require('./helpers.cjs')

test.describe('smoke', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('page loads with tree rows', async ({ page }) => {
    const rows = page.locator('[data-testid="tree-row"]')
    await expect(rows.first()).toBeVisible()
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
  })
})

test.describe('folder to open', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('expands known mac path', async ({ page }) => {
    await selectHost(page, 'brians-m2prombp')
    await setDirectorySearch(page, 'gas-m')

    await expect(page.locator('[data-testid="tree-row"][data-path$="/gas-meter-monitor"]')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"]', { hasText: 'gas-meter-monitor/' })).toBeVisible({ timeout: 20_000 })
  })

  test('expands known Windows path', async ({ page }) => {
    await selectHost(page, 'photoshop-pc')
    await setDirectorySearch(page, 'Scanner-Nikon')

    await expect(page.locator('[data-testid="tree-row"][data-path*="/scanner-nikon-4000"]')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"]', { hasText: 'Scanner-Nikon-4000/' })).toBeVisible({ timeout: 20_000 })
  })

  test('expands Windows matches across C and D', async ({ page }) => {
    await selectHost(page, 'photoshop-pc')
    await setDirectorySearch(page, 'Downloads')

    await expect(page.locator('[data-testid="tree-row"][data-path="__drive__:C"]')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"][data-path="__drive__:D"]')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"][data-path$="/downloads"][data-path^="__drive__:C"]').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"][data-path$="/downloads"][data-path^="__drive__:D"]').first()).toBeVisible({ timeout: 20_000 })
  })
})

test.describe('category filter', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
    await switchToListView(page)
  })

  test('selecting a category filters file rows', async ({ page }) => {
    const rowsBefore = await page.locator('[data-testid="tree-row"]').count()
    expect(rowsBefore).toBeGreaterThan(0)

    await applyFirstCategoryFilter(page)

    await expect(page.locator('[data-testid="file-type-filter"]')).not.toHaveText('All types')
    await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible()
  })
})

test.describe('category filter preserves tree dirs', () => {
  test('directories remain visible when filtering by category in tree view', async ({ page }) => {
    await gotoCleanAndSettle(page)
    await selectHost(page, 'brians-m2prombp')
    await setDirectorySearch(page, 'gas-m')

    await expect(page.locator('[data-testid="tree-row"][data-path$="/gas-meter-monitor"]')).toBeVisible({ timeout: 20_000 })
    const dirsBefore = await page.locator('[data-testid="tree-row"][data-entry-type="dir"]').count()
    expect(dirsBefore).toBeGreaterThan(0)

    await applyFirstCategoryFilter(page)

    const dirsAfter = await page.locator('[data-testid="tree-row"][data-entry-type="dir"]').count()
    expect(dirsAfter).toBeGreaterThan(0)
    await expect(page.locator('[data-testid="tree-row"][data-path$="/gas-meter-monitor"]')).toBeVisible({ timeout: 20_000 })
  })
})

test.describe('reset', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('reset clears category filter', async ({ page }) => {
    await switchToListView(page)
    await applyFirstCategoryFilter(page)

    await expect(page.locator('[data-testid="file-type-filter"]')).not.toHaveText('All types')

    await page.locator('[data-testid="reset-button"]').click()
    await waitForApiIdle(page)

    await expect(page.locator('[data-testid="file-type-filter"]')).toHaveText('All types')
  })
})
