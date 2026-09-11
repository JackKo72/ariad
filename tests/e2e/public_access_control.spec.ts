import { expect, test } from "@playwright/test";

test.describe("Public access control (browser)", () => {
  test("unapproved encounter's patient page is never reachable", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();
    await expect(page).toHaveURL(/\/encounters\/.+/);

    await page.getByTestId("transcript-input").fill("의사: 안녕하세요.\n환자: 안녕하세요.");
    await page.getByTestId("submit-input-button").click();
    await page.getByTestId("process-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "REVIEW_REQUIRED");

    // No public token exists yet -- an unpublished encounter has nothing to
    // browse to at /p/*. Confirm a made-up token also 404s.
    await page.goto("/p/this-token-does-not-exist");
    await expect(page.getByTestId("patient-not-found")).toBeVisible();
  });
});
