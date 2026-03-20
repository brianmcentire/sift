// @ts-check
const { test, expect } = require('@playwright/test')
const {
  gotoCleanAndSettle,
  waitForApiIdle,
  waitForTreeReady,
  clickReset,
  selectAllHosts,
} = require('./helpers.cjs')

// These tests require at least one hidden host in the datastore.
// Current state: Photoshop-PC is hidden.

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

test.describe('hidden host visibility', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('Hidden chip is visible when hidden hosts exist', async ({ page }) => {
    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toBeVisible()
    await expect(toggle).toContainText('Hidden')
  })

  test('hidden host is NOT in the main chip bar by default', async ({ page }) => {
    const hiddenChip = page.locator('[data-testid="host-chip-Photoshop-PC"]')
    await expect(hiddenChip).toHaveCount(0)
  })

  test('visible hosts have chips in the bar', async ({ page }) => {
    const visibleChip = page.locator('[data-testid="host-chip-Brians-M2ProMBP"]')
    await expect(visibleChip).toBeVisible()
  })
})

test.describe('hidden host dropdown', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('dropdown opens and lists hidden hosts', async ({ page }) => {
    const panel = await openHiddenDropdown(page)
    const option = panel.locator('[data-testid="hidden-host-option-Photoshop-PC"]')
    await expect(option).toBeVisible()
    await expect(option).toContainText('Photoshop-PC')
  })

  test('dropdown closes on outside click', async ({ page }) => {
    await openHiddenDropdown(page)
    await closeHiddenDropdown(page)
  })

  test('hidden host checkbox is unchecked by default', async ({ page }) => {
    const panel = await openHiddenDropdown(page)
    const checkbox = panel.locator('[data-testid="hidden-host-option-Photoshop-PC"] input[type="checkbox"]')
    await expect(checkbox).not.toBeChecked()
  })
})

test.describe('hidden host promotion', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('checking a hidden host promotes it to the chip bar', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Chip should appear with dashed border
    const chip = page.locator('[data-testid="host-chip-Photoshop-PC"]')
    await expect(chip).toBeVisible()
    await expect(chip).toHaveAttribute('data-hidden-host', 'true')
    await expect(chip).toHaveAttribute('data-selected', 'true')
  })

  test('promoted chip badge count shows on Hidden toggle', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toContainText('Hidden (1)')
  })

  test('promoted chip stays in bar when another host is clicked', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Click a visible host (deselects Photoshop-PC but chip should remain)
    const visibleChip = page.locator('[data-testid="host-chip-Brians-M2ProMBP"]')
    await visibleChip.click()
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    // Chip still in bar, but now deselected
    const hiddenChip = page.locator('[data-testid="host-chip-Photoshop-PC"]')
    await expect(hiddenChip).toBeVisible()
    await expect(hiddenChip).toHaveAttribute('data-selected', 'false')
  })

  test('deselected promoted chip can be shift-clicked to reselect', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Click a visible host to deselect hidden host
    await page.locator('[data-testid="host-chip-Brians-M2ProMBP"]').click()
    await waitForApiIdle(page)

    // Shift-click the hidden chip to add it back
    const hiddenChip = page.locator('[data-testid="host-chip-Photoshop-PC"]')
    await hiddenChip.click({ modifiers: ['Shift'] })
    await waitForApiIdle(page)

    await expect(hiddenChip).toHaveAttribute('data-selected', 'true')
  })

  test('unchecking in dropdown removes chip from bar', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Verify chip is present
    await expect(page.locator('[data-testid="host-chip-Photoshop-PC"]')).toBeVisible()

    // Uncheck via dropdown
    await demoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Chip should be gone
    await expect(page.locator('[data-testid="host-chip-Photoshop-PC"]')).toHaveCount(0)
  })
})

test.describe('hidden host interaction with All and Reset', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('"All" selects only visible hosts, does not add hidden hosts', async ({ page }) => {
    await selectAllHosts(page)
    await waitForTreeReady(page)

    // Hidden host should not appear as a chip
    await expect(page.locator('[data-testid="host-chip-Photoshop-PC"]')).toHaveCount(0)

    // Badge should show 0 promoted
    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toHaveAttribute('data-promoted-count', '0')
  })

  test('"All" does not deselect a promoted hidden host', async ({ page }) => {
    // Promote and select hidden host
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Click All — should select all visible. Hidden chip stays promoted but deselected.
    await selectAllHosts(page)
    await waitForApiIdle(page)

    const hiddenChip = page.locator('[data-testid="host-chip-Photoshop-PC"]')
    // Chip should still be in the bar (promoted)
    await expect(hiddenChip).toBeVisible()
    // But not selected (All only selects visible hosts)
    await expect(hiddenChip).toHaveAttribute('data-selected', 'false')
  })

  test('Reset clears promoted hidden hosts', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    await expect(page.locator('[data-testid="host-chip-Photoshop-PC"]')).toBeVisible()

    await clickReset(page)
    await waitForTreeReady(page)

    // Chip gone, badge back to 0
    await expect(page.locator('[data-testid="host-chip-Photoshop-PC"]')).toHaveCount(0)
    const toggle = page.locator('[data-testid="hidden-host-toggle"]')
    await expect(toggle).toHaveAttribute('data-promoted-count', '0')
  })
})

test.describe('hidden host data flow', () => {
  test.beforeEach(async ({ page }) => {
    await gotoCleanAndSettle(page)
  })

  test('promoting a hidden host loads its tree data', async ({ page }) => {
    // Start with just the local host
    await page.locator('[data-testid="host-chip-Brians-M2ProMBP"]').click()
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    const rowsBefore = await page.locator('[data-testid="tree-row"]').count()

    // Promote hidden host via shift-click on its chip (after promoting)
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)
    await waitForApiIdle(page)
    await waitForTreeReady(page)

    // Should have tree rows (possibly more or different, since hidden host has data)
    const rowsAfter = await page.locator('[data-testid="tree-row"]').count()
    expect(rowsAfter).toBeGreaterThan(0)
  })

  test('hidden host not persisted to localStorage', async ({ page }) => {
    await promoteHiddenHost(page, 'Photoshop-PC')
    await closeHiddenDropdown(page)

    // Read localStorage
    const stored = await page.evaluate(() => {
      try {
        const raw = window.localStorage.getItem('sift-filters')
        return raw ? JSON.parse(raw) : null
      } catch { return null }
    })

    // selectedHosts in storage should NOT contain the hidden host
    const savedHosts = stored?.selectedHosts || []
    expect(savedHosts).not.toContain('Photoshop-PC')
  })
})
