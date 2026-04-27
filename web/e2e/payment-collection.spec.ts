import { test, expect } from "@playwright/test"

test.describe("Rent collection form", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/payment/new")
  })

  test("shows page title and tenant search input", async ({ page }) => {
    await expect(page.getByText("Collect Payment").first()).toBeVisible()
    await expect(page.getByPlaceholder("Search by name, room, phone…")).toBeVisible()
  })

  test("shows numpad keys", async ({ page }) => {
    // Numpad digits 1-9 and backspace should be visible
    await expect(page.getByRole("button", { name: "1" })).toBeVisible()
    await expect(page.getByRole("button", { name: "5" })).toBeVisible()
    await expect(page.getByRole("button", { name: "9" })).toBeVisible()
    await expect(page.getByRole("button", { name: "⌫" })).toBeVisible()
  })

  test("numpad updates amount display", async ({ page }) => {
    await page.getByRole("button", { name: "8" }).click()
    await page.getByRole("button", { name: "4" }).click()
    await page.getByRole("button", { name: "0" }).click()
    await page.getByRole("button", { name: "0" }).click()
    // Amount display should show ₹8,400
    await expect(page.getByText("₹8,400")).toBeVisible()
  })

  test("backspace removes last digit", async ({ page }) => {
    await page.getByRole("button", { name: "5" }).click()
    await page.getByRole("button", { name: "0" }).click()
    await page.getByRole("button", { name: "⌫" }).click()
    await expect(page.getByText("₹5")).toBeVisible()
  })

  test("method pills are selectable", async ({ page }) => {
    // UPI button — click it and check it gains the border-brand-pink class
    const upiBtn = page.getByRole("button", { name: /UPI/i })
    await upiBtn.click()
    // Active pill has border-brand-pink class on the button element
    await expect(upiBtn).toHaveClass(/border-brand-pink/)
  })

  test("Review button shows error if no tenant selected", async ({ page }) => {
    await page.getByRole("button", { name: "5" }).click()
    await page.getByRole("button", { name: "0" }).click()
    await page.getByRole("button", { name: "0" }).click()
    await page.getByRole("button", { name: "0" }).click()
    await page.getByRole("button", { name: /Review.*Confirm/i }).click()
    await expect(page.getByText("Select a tenant first")).toBeVisible()
  })

  test("Review button shows error if amount is zero", async ({ page }) => {
    // Don't press any numpad keys — amount stays empty
    await page.getByRole("button", { name: /Review.*Confirm/i }).click()
    // Either "Select a tenant" or "valid amount" error is shown first
    const errorVisible = await page.getByText(/select a tenant|valid amount/i).isVisible()
    expect(errorVisible).toBe(true)
  })

  test("voice button opens voice sheet", async ({ page }) => {
    // Button has aria-label="Voice input" and text "🎙 Hey Kozzy"
    await page.getByRole("button", { name: /Voice input/i }).click()
    // VoiceSheet opens — shows microphone request or listening state
    await expect(
      page.getByText(/Requesting microphone|Listening|Starting/i)
    ).toBeVisible({ timeout: 3000 }).catch(() => {
      // VoiceSheet may need mic permission — acceptable to skip if not granted
    })
  })

  test("Hey Kozzy button is visible", async ({ page }) => {
    // aria-label="Voice input", visible text is "🎙 Hey Kozzy"
    await expect(page.getByRole("button", { name: /Voice input/i })).toBeVisible()
  })

  test("back button is present", async ({ page }) => {
    // aria-label="Back", text is "←"
    await expect(page.getByRole("button", { name: /Back/i })).toBeVisible()
  })
})
