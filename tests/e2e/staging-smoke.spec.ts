import { expect, test } from "@playwright/test";

test.describe("staging authenticated smoke", () => {
  test.skip(!process.env.STAGING_AUTH_STATE, "Set STAGING_AUTH_STATE to run authenticated staging smoke tests.");

  test.use({ storageState: process.env.STAGING_AUTH_STATE });

  test("authenticated app surfaces core post-MVP actions", async ({ page }) => {
    await page.goto("/app");

    await expect(page.getByText("Search your memory")).toBeVisible();
    await expect(page.getByText("Follow-ups")).toBeVisible();
  });
});
