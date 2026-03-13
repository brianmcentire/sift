// @ts-check
const { test, expect } = require('@playwright/test')

// Requires: sift server running on :8765 and `make dev-frontend` on :5173

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function waitForApiIdle(page, timeout = 30_000) {
  const badge = page.locator('[data-testid="api-activity"]')
  await expect(badge).toBeVisible({ timeout })
  await expect(badge).toHaveAttribute('data-state', 'idle', { timeout })
  await expect(badge).toHaveAttribute('data-count', '0', { timeout })
}

async function waitForTreeReady(page, timeout = 30_000) {
  const rows = page.locator('[data-testid="tree-row"]')
  await expect.poll(async () => {
    const count = await rows.count()
    const hasEmptyState = await page.getByText('No files found.').isVisible().catch(() => false)
    return { count, hasEmptyState }
  }, { timeout }).toEqual(expect.objectContaining({ hasEmptyState: false }))
  await expect(rows.first()).toBeVisible({ timeout })
}

async function gotoCleanAndSettle(page) {
  await page.addInitScript(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })
  await page.goto('/')
  await waitForApiIdle(page)
  await waitForTreeReady(page, 20_000)
}

async function selectHost(page, hostName) {
  const hostButton = page.locator('header button').filter({
    hasText: new RegExp(`^${escapeRegex(hostName)}$`),
  })
  await expect(hostButton).toBeVisible({ timeout: 10_000 })
  await hostButton.click()
  await waitForApiIdle(page)
  await waitForTreeReady(page)
}

async function switchToListView(page) {
  const modeBtn = page.locator('button', { hasText: /sift · Tree View/i })
  await expect(modeBtn).toBeVisible({ timeout: 10_000 })
  await modeBtn.click()
  await waitForApiIdle(page)
  await waitForTreeReady(page, 20_000)
}

async function setDirectorySearch(page, query) {
  const input = page.locator('[data-testid="directory-search"]')
  await expect(input).toBeVisible({ timeout: 10_000 })
  await input.fill(query)
  await page.waitForTimeout(500)
  await waitForApiIdle(page)
}

async function applyFirstCategoryFilter(page) {
  await page.locator('[data-testid="file-type-filter"]').click()
  const firstChip = page.locator('[data-testid^="category-chip-"]').first()
  await expect(firstChip).toBeVisible({ timeout: 10_000 })
  await firstChip.click()
  await page.locator('header').click({ position: { x: 5, y: 5 } })
  await waitForApiIdle(page)
}

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
    await selectHost(page, 'Brians-M2ProMBP')
    await setDirectorySearch(page, 'gas-m')

    await expect(page.locator('[data-testid="tree-row"][data-path$="/gas-meter-monitor"]')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"]', { hasText: 'gas-meter-monitor/' })).toBeVisible({ timeout: 20_000 })
  })

  test('expands known Windows path', async ({ page }) => {
    await selectHost(page, 'Photoshop-PC')
    await setDirectorySearch(page, 'Scanner-Nikon')

    await expect(page.locator('[data-testid="tree-row"][data-path*="/scanner-nikon-4000"]')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-testid="tree-row"]', { hasText: 'Scanner-Nikon-4000/' })).toBeVisible({ timeout: 20_000 })
  })

  test('expands Windows matches across C and D', async ({ page }) => {
    await selectHost(page, 'Photoshop-PC')
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
    await selectHost(page, 'Brians-M2ProMBP')
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
