// @ts-check
const { expect } = require('@playwright/test')

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
  const modeBtn = page.locator('[data-testid="view-mode"]')
  const text = await modeBtn.textContent()
  if (text && /List View/i.test(text)) return // already in list view
  await modeBtn.click()
  await waitForApiIdle(page)
  await waitForTreeReady(page, 20_000)
}

async function switchToTreeView(page) {
  const modeBtn = page.locator('[data-testid="view-mode"]')
  const text = await modeBtn.textContent()
  if (text && /Tree View/i.test(text)) return // already in tree view
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

async function setMinSize(page, label) {
  await page.locator('[data-testid="min-size-filter"]').click()
  const preset = page.locator('button', { hasText: new RegExp(`^${escapeRegex(label)}$`) })
  await expect(preset).toBeVisible({ timeout: 5_000 })
  await preset.click()
  await waitForApiIdle(page)
}

async function toggleDupOnly(page) {
  await page.locator('[data-testid="dup-only-toggle"]').click()
  await waitForApiIdle(page)
}

async function setHashSearch(page, query) {
  const input = page.locator('[data-testid="hash-search"]')
  await expect(input).toBeVisible({ timeout: 10_000 })
  await input.fill(query)
  await page.waitForTimeout(500)
  await waitForApiIdle(page)
}

async function clickReset(page) {
  await page.locator('[data-testid="reset-button"]').click()
  await waitForApiIdle(page)
}

module.exports = {
  escapeRegex,
  waitForApiIdle,
  waitForTreeReady,
  gotoCleanAndSettle,
  selectHost,
  switchToListView,
  switchToTreeView,
  setDirectorySearch,
  applyFirstCategoryFilter,
  setMinSize,
  toggleDupOnly,
  setHashSearch,
  clickReset,
}
