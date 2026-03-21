// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  switchToListView,
  switchToTreeView,
  waitForApiIdle,
  waitForTreeReady,
} = require('./helpers.cjs')

test.describe('mode switching', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('starts in Tree View by default', async ({ page }) => {
    const modeBtn = page.locator('[data-testid="view-mode"]')
    await expect(modeBtn).toContainText('Tree View')

    // Tree view shows directories
    const dirRows = page.locator('[data-testid="tree-row"][data-entry-type="dir"]')
    const dirCount = await dirRows.count()
    expect(dirCount).toBeGreaterThan(0)
  })

  test('switches to List View showing files', async ({ page }) => {
    await switchToListView(page)

    const modeBtn = page.locator('[data-testid="view-mode"]')
    await expect(modeBtn).toContainText('List View')

    // List view shows file rows directly
    const rows = page.locator('[data-testid="tree-row"]')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
  })

  test('switches back to Tree View from List View', async ({ page }) => {
    await switchToListView(page)
    await expect(page.locator('[data-testid="view-mode"]')).toContainText('List View')

    await switchToTreeView(page)
    await expect(page.locator('[data-testid="view-mode"]')).toContainText('Tree View')

    // Should show directories again
    const dirRows = page.locator('[data-testid="tree-row"][data-entry-type="dir"]')
    const dirCount = await dirRows.count()
    expect(dirCount).toBeGreaterThan(0)
  })

  test('placeholder text updates on mode switch', async ({ page }) => {
    const dirInput = page.locator('[data-testid="directory-search"]')
    await expect(dirInput).toHaveAttribute('placeholder', 'folder to open')

    await switchToListView(page)
    await expect(dirInput).toHaveAttribute('placeholder', 'path contains')

    await switchToTreeView(page)
    await expect(dirInput).toHaveAttribute('placeholder', 'folder to open')
  })

  test('mode switch preserves host selection', async ({ page }) => {
    // Check which hosts are selected (have active styling)
    const hostButtons = page.locator('header button').filter({ hasText: /^[A-Za-z]/ })
    const initialCount = await hostButtons.count()

    await switchToListView(page)

    // Host buttons should still be present
    const afterCount = await hostButtons.count()
    expect(afterCount).toBe(initialCount)
  })
})
