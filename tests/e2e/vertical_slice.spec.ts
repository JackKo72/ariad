import { expect, test } from "@playwright/test";

const TRANSCRIPT = "의사: 오늘 혈압이 조금 높게 나왔어요.\n환자: 요즘 짜게 먹었어요.\n의사: 혈압약 5mg 하루 한 번 드세요.";

test.describe("Task 01 vertical slice", () => {
  test("create -> input -> process -> edit -> approve -> publish -> patient view -> refresh -> revoke", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();

    await expect(page).toHaveURL(/\/encounters\/.+/);
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "DRAFT");

    await page.getByTestId("transcript-input").fill(TRANSCRIPT);
    await page.getByTestId("submit-input-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "SUBMITTED");

    await page.getByTestId("process-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "REVIEW_REQUIRED");
    await expect(page.getByTestId("problems-input")).not.toHaveValue("");

    // Clinician edit: add a grounded (verbatim) medication instruction.
    await page.getByTestId("field-medication_instructions").fill("의사: 혈압약 5mg 하루 한 번 드세요.");
    await page.getByTestId("save-draft-button").click();
    await expect(page.getByTestId("field-medication_instructions")).toHaveValue(
      "의사: 혈압약 5mg 하루 한 번 드세요.",
    );

    await page.getByTestId("approve-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "APPROVED");

    await page.getByTestId("publish-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "PUBLISHED");

    const publicHref = await page.getByTestId("public-link").getAttribute("href");
    expect(publicHref).toBeTruthy();

    await page.goto(publicHref!);
    await expect(page.getByTestId("patient-explanation")).toBeVisible();
    await expect(page.getByText("의사: 혈압약 5mg 하루 한 번 드세요.").first()).toBeVisible();

    // Refresh: state must persist (not just client-side memory).
    await page.reload();
    await expect(page.getByTestId("patient-explanation")).toBeVisible();

    await page.goBack();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "PUBLISHED");
    await page.reload();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "PUBLISHED");

    await page.getByTestId("revoke-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "REVOKED");

    await page.goto(publicHref!);
    await expect(page.getByTestId("patient-not-found")).toBeVisible();
  });
});
