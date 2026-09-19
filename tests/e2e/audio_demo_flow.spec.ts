import { expect, test } from "@playwright/test";

test.describe("Task 02 Phase C: demo sample flow (no API key)", () => {
  test("샘플 음성 사용 → 역할 확인 → 승인 → 환자 페이지에 승인 설명만 표시", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();
    await expect(page).toHaveURL(/\/encounters\/.+/);
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "DRAFT");

    await page.getByTestId("input-method-sample").click();
    await expect(page.getByTestId("demo-result-notice")).toBeVisible();
    await page.getByTestId("select-sample-button").click();

    // Selecting the sample runs ASR synchronously and advances to SUBMITTED
    // with role confirmation pending -- never auto-continuing past it.
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "SUBMITTED");
    await expect(page.getByTestId("role-select-A")).toBeVisible();
    await expect(page.getByTestId("role-select-B")).toBeVisible();

    await page.getByTestId("role-select-A").selectOption("doctor");
    await page.getByTestId("role-select-B").selectOption("patient");
    await page.getByTestId("confirm-roles-button").click();

    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "REVIEW_REQUIRED");
    // Demo structure/explanation (from the sidecar fixture) should be visible,
    // not an empty mock-echo.
    await expect(page.getByTestId("field-medication_instructions")).not.toHaveValue("");

    await page.getByTestId("approve-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "APPROVED");

    await page.getByTestId("publish-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "PUBLISHED");

    const publicHref = await page.getByTestId("public-link").getAttribute("href");
    await page.goto(publicHref!);
    await expect(page.getByTestId("patient-explanation")).toBeVisible();
    await expect(page.getByText("리시노프릴").first()).toBeVisible();
  });
});
