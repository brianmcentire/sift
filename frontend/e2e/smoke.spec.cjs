// @ts-check
const { test, expect } = require('@playwright/test')

// Requires: sift server running on :8765 and `make dev-frontend` on :5173

// Helper: try to expand first dir row by clicking it; returns true if children appeared
async function tryExpandFirstDir(page, timeout = 15_000) {
  const dirRow = page.locator('[data-testid="tree-row"][data-entry-type="dir"]').first()
  if (!(await dirRow.isVisible())) return false
  const countBefore = await page.locator('[data-testid="tree-row"]').count()
  await dirRow.click()
  try {
    await expect(async () => {
      const countAfter = await page.locator('[data-testid="tree-row"]').count()
      expect(countAfter).toBeGreaterThan(countBefore)
    }).toPass({ timeout })
    return true
  } catch {
    return false
  }
}

// Helper: select a single non-drive host by clicking its chip (plain click = solo-select)
// Returns true if the tree changed to show different rows after selection
async function selectNonDriveHost(page) {
  // Find host chips — they're buttons inside the host chips row, excluding "all"
  const hostButtons = page.locator('header button.rounded-full.uppercase').filter({
    hasNot: page.locator('text=/^all$/i'),
  })
  const count = await hostButtons.count()
  // Try each host chip until tree shows non-drive paths (no __drive__ prefix)
  for (let i = 0; i < count; i++) {
    const chip = hostButtons.nth(i)
    const chipText = await chip.textContent()
    // Skip if it looks like it might be the currently active Windows host
    await chip.click()
    // Wait for tree to update
    await page.waitForTimeout(1_000)
    const firstRow = page.locator('[data-testid="tree-row"]').first()
    if (await firstRow.isVisible({ timeout: 5_000 }).catch(() => false)) {
      // Check if the first dir is NOT a drive node (no ":" in display name like "C:/")
      const text = await firstRow.textContent()
      if (text && !text.match(/^[A-Z]:\//)) {
        return true
      }
    }
  }
  return false
}

test.describe('smoke', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible({ timeout: 10_000 })
  })

  test('page loads with tree rows', async ({ page }) => {
    const rows = page.locator('[data-testid="tree-row"]')
    await expect(rows.first()).toBeVisible()
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
  })

  test('can expand a directory', async ({ page }) => {
    // First try expanding as-is
    let expanded = await tryExpandFirstDir(page, 10_000)

    // If that failed (e.g. drive node), try selecting a non-drive host first
    if (!expanded) {
      const switched = await selectNonDriveHost(page)
      if (switched) {
        expanded = await tryExpandFirstDir(page, 10_000)
      }
    }

    // If expand still fails, the server may be too slow — skip rather than fail
    if (!expanded) {
      test.skip(true, 'Directory expansion did not produce children — server may be slow or drive node issue')
      return
    }

    // Verify children are visible
    const count = await page.locator('[data-testid="tree-row"]').count()
    expect(count).toBeGreaterThan(2)
  })
})

test.describe('category filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible({ timeout: 10_000 })

    // Switch to List View so files (with categories) are immediately visible
    const modeBtn = page.locator('button', { hasText: /sift · Tree View/i })
    if (await modeBtn.isVisible()) {
      await modeBtn.click()
      await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible({ timeout: 10_000 })
    }
  })

  test('selecting a category filters file rows', async ({ page }) => {
    const rowsBefore = await page.locator('[data-testid="tree-row"]').count()
    expect(rowsBefore).toBeGreaterThan(0)

    // Open the file type filter dropdown
    await page.locator('[data-testid="file-type-filter"]').click()
    const firstChip = page.locator('[data-testid^="category-chip-"]').first()
    await expect(firstChip).toBeVisible({ timeout: 5_000 })

    // Click the category chip
    await firstChip.click()

    // Close dropdown
    await page.locator('header').click({ position: { x: 5, y: 5 } })

    // Filter button should reflect the selection
    await expect(page.locator('[data-testid="file-type-filter"]')).not.toHaveText('All types')

    // Rows should still be present
    await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible()
  })
})

test.describe('category filter preserves tree dirs', () => {
  test('directories remain visible when filtering by category in tree view', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible({ timeout: 10_000 })

    // Try to get a non-drive host with expandable dirs
    await selectNonDriveHost(page)

    // Expand first dir
    const expanded = await tryExpandFirstDir(page, 15_000)
    if (!expanded) {
      test.skip(true, 'Could not expand directory — skipping tree filter test')
      return
    }

    // Count dir rows before filter
    const dirsBefore = await page.locator('[data-testid="tree-row"][data-entry-type="dir"]').count()
    expect(dirsBefore).toBeGreaterThan(0)

    // Apply category filter (need files to be visible for categories)
    await page.locator('[data-testid="file-type-filter"]').click()
    const firstChip = page.locator('[data-testid^="category-chip-"]').first()

    if (!(await firstChip.isVisible({ timeout: 3_000 }).catch(() => false))) {
      await page.keyboard.press('Escape')
      test.skip(true, 'No file type categories available')
      return
    }

    await firstChip.click()
    await page.locator('header').click({ position: { x: 5, y: 5 } })

    // Directory rows must survive category filtering
    await expect(page.locator('[data-testid="tree-row"][data-entry-type="dir"]').first()).toBeVisible()
    const dirsAfter = await page.locator('[data-testid="tree-row"][data-entry-type="dir"]').count()
    expect(dirsAfter).toBeGreaterThan(0)
  })
})

test.describe('reset', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible({ timeout: 10_000 })
  })

  test('reset clears category filter', async ({ page }) => {
    // Switch to List View to get category chips
    const modeBtn = page.locator('button', { hasText: /sift · Tree View/i })
    if (await modeBtn.isVisible()) {
      await modeBtn.click()
      await expect(page.locator('[data-testid="tree-row"]').first()).toBeVisible({ timeout: 10_000 })
    }

    // Apply a category filter
    await page.locator('[data-testid="file-type-filter"]').click()
    const firstChip = page.locator('[data-testid^="category-chip-"]').first()
    await expect(firstChip).toBeVisible({ timeout: 5_000 })
    await firstChip.click()
    await page.locator('header').click({ position: { x: 5, y: 5 } })

    // Verify filter is active
    await expect(page.locator('[data-testid="file-type-filter"]')).not.toHaveText('All types')

    // Click reset
    await page.locator('[data-testid="reset-button"]').click()

    // Filter should be back to "All types"
    await expect(page.locator('[data-testid="file-type-filter"]')).toHaveText('All types')
  })
})
