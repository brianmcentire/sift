// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  waitForApiIdle,
  waitForTreeReady,
  clickReset,
  selectAllHosts,
} = require('./helpers.cjs')

// Discover hidden/visible hosts from the live server at suite startup.
// Tests skip if preconditions aren't met (no hidden hosts, etc.).
let HIDDEN_HOST = null   // first hidden host name
let VISIBLE_HOST = null  // first visible host with files

test.beforeAll(async ({ request }) => {
  const resp = await request.get('/hosts')
  const hosts = await resp.json()
  const hidden = hosts.find(h => h.hidden)
  const visible = hosts.find(h => !h.hidden && h.total_files > 0)
  HIDDEN_HOST = hidden?.host || null
  VISIBLE_HOST = visible?.host || null
})

/** Open the Hidden dropdown panel. */
async function openHiddenDropdown(page) {
  const toggle = page.locator('[data-testid="hidden-host-toggle"]')
  await expect(toggle).toBeVisible({ timeout: 10_000 })
  const panel = page.locator('[data-testid="hidden-host-panel"]')
  if (!(await panel.isVisible().catch(() => false))) {
    await toggle.click()
  }
  await expect(panel).toBeVisible({ timeout: 5_000 })
  return panel
}

/** Check (promote) a hidden host by name. */
async function promoteHiddenHost(page, hostName) {
  const panel = await openHiddenDropdown(page)
  const option = panel.locator(`[data-testid="hidden-host-option-${hostName}"]`)
  const checkbox = option.locator('input[type="checkbox"]')
  if (!(await checkbox.isChecked())) {
    await checkbox.click()
  }
  await waitForApiIdle(page)
}

/** Uncheck (demote) a hidden host by name. */
async function demoteHiddenHost(page, hostName) {
  const panel = await openHiddenDropdown(page)
  const option = panel.locator(`[data-testid="hidden-host-option-${hostName}"]`)
  const checkbox = option.locator('input[type="checkbox"]')
  if (await checkbox.isChecked()) {
    await checkbox.click()
  }
  await waitForApiIdle(page)
}

/** Close the dropdown by clicking outside it. */
async function closeHiddenDropdown(page) {
  await page.locator('header').click({ position: { x: 5, y: 5 } })
  await expect(page.locator('[data-testid="hidden-host-panel"]')).toHaveCount(0)
}

function skipUnlessHidden(testFn) {
  testFn.skip(() => !HIDDEN_HOST, 'no hidden hosts in datastore')
}

test.describe('hidden host visibility', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('Hidden chip is visible when hidden hosts exist', async ({ page }) => {
    test.skip(!HIDDEN_HOST, 'no hidden hosts in datastore')
    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toBeVisible()
    await expect(toggle).toContainText('Hidden')
  })

  test('hidden host is NOT in the main chip bar by default', async ({ page }) => {
    test.skip(!HIDDEN_HOST, 'no hidden hosts in datastore')
    const hiddenChip = page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)
    await expect(hiddenChip).toHaveCount(0)
  })

  test('visible hosts have chips in the bar', async ({ page }) => {
    test.skip(!VISIBLE_HOST, 'no visible hosts in datastore')
    const visibleChip = page.locator(`[data-testid="host-chip-${VISIBLE_HOST}"]`)
    await expect(visibleChip).toBeVisible()
  })
})

test.describe('hidden host dropdown', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!HIDDEN_HOST, 'no hidden hosts in datastore')
    await gotoCleanAndSettle(page)
  })

  test('dropdown opens and lists hidden hosts', async ({ page }) => {
    const panel = await openHiddenDropdown(page)
    const option = panel.locator(`[data-testid="hidden-host-option-${HIDDEN_HOST}"]`)
    await expect(option).toBeVisible()
    await expect(option).toContainText(HIDDEN_HOST)
  })

  test('dropdown closes on outside click', async ({ page }) => {
    await openHiddenDropdown(page)
    await closeHiddenDropdown(page)
  })

  test('hidden host checkbox is unchecked by default', async ({ page }) => {
    const panel = await openHiddenDropdown(page)
    const checkbox = panel.locator(`[data-testid="hidden-host-option-${HIDDEN_HOST}"] input[type="checkbox"]`)
    await expect(checkbox).not.toBeChecked()
  })
})

test.describe('hidden host promotion', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!HIDDEN_HOST, 'no hidden hosts in datastore')
    await gotoCleanAndSettle(page)
  })

  test('checking a hidden host promotes it to the chip bar', async ({ page }) => {
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    const chip = page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)
    await expect(chip).toBeVisible()
    await expect(chip).toHaveAttribute('data-hidden-host', 'true')
    await expect(chip).toHaveAttribute('data-selected', 'true')
  })

  test('promoted chip badge count shows on Hidden toggle', async ({ page }) => {
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toContainText('Hidden (1)')
  })

  test('promoted chip stays in bar when another host is clicked', async ({ page }) => {
    test.skip(!VISIBLE_HOST, 'no visible hosts in datastore')
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    // Click a visible host (deselects hidden host but chip should remain)
    const visibleChip = page.locator(`[data-testid="host-chip-${VISIBLE_HOST}"]`)
    await visibleChip.click()
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    // Chip still in bar, but now deselected
    const hiddenChip = page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)
    await expect(hiddenChip).toBeVisible()
    await expect(hiddenChip).toHaveAttribute('data-selected', 'false')
  })

  test('deselected promoted chip can be shift-clicked to reselect', async ({ page }) => {
    test.skip(!VISIBLE_HOST, 'no visible hosts in datastore')
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    // Click a visible host to deselect hidden host
    await page.locator(`[data-testid="host-chip-${VISIBLE_HOST}"]`).click()
    await waitForApiIdle(page)

    // Shift-click the hidden chip to add it back
    const hiddenChip = page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)
    await hiddenChip.click({ modifiers: ['Shift'] })
    await waitForApiIdle(page)

    await expect(hiddenChip).toHaveAttribute('data-selected', 'true')
  })

  test('unchecking in dropdown removes chip from bar', async ({ page }) => {
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    await expect(page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)).toBeVisible()

    // Uncheck via dropdown
    await demoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    await expect(page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)).toHaveCount(0)
  })
})

test.describe('hidden host interaction with All and Reset', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!HIDDEN_HOST, 'no hidden hosts in datastore')
    await gotoCleanAndSettle(page)
  })

  test('"All" selects only visible hosts, does not add hidden hosts', async ({ page }) => {
    await selectAllHosts(page)
    await waitForTreeReady(page)

    await expect(page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)).toHaveCount(0)

    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toHaveAttribute('data-promoted-count', '0')
  })

  test('"All" does not deselect a promoted hidden host', async ({ page }) => {
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    await selectAllHosts(page)
    await waitForApiIdle(page)

    const hiddenChip = page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)
    await expect(hiddenChip).toBeVisible()
    await expect(hiddenChip).toHaveAttribute('data-selected', 'false')
  })

  test('Reset clears promoted hidden hosts', async ({ page }) => {
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    await expect(page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)).toBeVisible()

    await clickReset(page)
    await waitForTreeReady(page)

    await expect(page.locator(`[data-testid="host-chip-${HIDDEN_HOST}"]`)).toHaveCount(0)
    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toHaveAttribute('data-promoted-count', '0')
  })
})

test.describe('hidden host data flow', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!HIDDEN_HOST, 'no hidden hosts in datastore')
    await gotoCleanAndSettle(page)
  })

  test('promoting a hidden host loads its tree data', async ({ page }) => {
    test.skip(!VISIBLE_HOST, 'no visible hosts in datastore')
    // Start with just a visible host
    await page.locator(`[data-testid="host-chip-${VISIBLE_HOST}"]`).click()
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    // Promote hidden host
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    const rowsAfter = await page.locator('[data-testid="tree-row"]').count()
    expect(rowsAfter).toBeGreaterThan(0)
  })

  test('hidden host not persisted to localStorage', async ({ page }) => {
    await promoteHiddenHost(page, HIDDEN_HOST)
    await closeHiddenDropdown(page)

    const stored = await page.evaluate(() => {
      try {
        const raw = window.localStorage.getItem('sift-filters')
        return raw ? JSON.parse(raw) : null
      } catch { return null }
    })

    const savedHosts = stored?.selectedHosts || []
    expect(savedHosts).not.toContain(HIDDEN_HOST)
  })
})

test.describe('no hidden hosts graceful behavior', () => {
  test('app loads normally when no hosts are hidden', async ({ page }) => {
    // This test always runs — verifies the Hidden chip is absent when appropriate
    await gotoCleanAndSettle(page)
    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    if (!HIDDEN_HOST) {
      await expect(toggle).toHaveCount(0)
    } else {
      await expect(toggle).toBeVisible()
    }
  })
})
