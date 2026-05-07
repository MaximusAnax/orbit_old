import { test, expect } from "@playwright/test";

test("landing page shows the capture-first value proposition", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Turn the messy note in your head into someone you can actually remember.")).toBeVisible();
  await expect(page.getByPlaceholder("Met Alex from Figma after the hackathon dinner...")).toBeVisible();
  await expect(page.getByText("Save to my memory")).toBeVisible();
});
