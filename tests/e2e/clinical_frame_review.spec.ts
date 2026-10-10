import { expect, test } from "@playwright/test";

// tasks/10_CLINICAL_FRAME_AND_REVIEW.md: frame selection is recorded, and a
// negative decision blocks approval until the clinician checks it. The mock
// LLM never fills `decisions`, so the decision is added through the same
// draft-edit API the review screen uses.
const API = "http://localhost:8000";
const TRANSCRIPT = "의사: 막힌 혈관을 뚫는 시술은 지금은 안 하겠습니다.\n보호자: 네, 알겠습니다.";

test("stroke frame is recorded and a 'not doing' decision gates approval", async ({ page, request }) => {
  await page.goto("/");
  await page.getByTestId("consent-checkbox").check();
  await page.getByTestId("create-encounter-button").click();
  await expect(page).toHaveURL(/\/encounters\/.+/);
  const encounterId = page.url().split("/encounters/")[1];

  await page.getByTestId("transcript-input").fill(TRANSCRIPT);
  await page.getByTestId("submit-input-button").click();
  await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "SUBMITTED");

  await page.getByTestId("clinical-frame-select").selectOption("stroke");
  await page.getByTestId("process-button").click();
  await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "REVIEW_REQUIRED");
  await expect(page.getByTestId("clinical-frame-label")).toContainText("뇌졸중");
  await expect(page.getByTestId("approve-button")).toBeEnabled(); // empty checklist

  const detail = await (await request.get(`${API}/encounters/${encounterId}`)).json();
  const draft = detail.draft_version;
  const patched = await request.patch(`${API}/encounters/${encounterId}/draft`, {
    data: {
      structure: {
        ...draft.structure,
        decisions: [
          {
            text: "막힌 혈관을 뚫는 시술",
            status: "decided_not_to_do",
            condition: "지금보다 많이 나빠지면 다시 고려",
            rationale: "",
            source_segment_ids: ["seg-1"],
            needs_confirmation: false,
          },
        ],
      },
      explanation: draft.explanation,
      expected_version_number: draft.version_number,
    },
  });
  expect(patched.ok()).toBeTruthy();

  await page.reload();
  await expect(page.getByTestId("slot-decisions")).toContainText("[하지 않음] 막힌 혈관을 뚫는 시술");
  await expect(page.getByTestId("review-checklist")).toContainText("0/1");
  await expect(page.getByTestId("approve-button")).toBeDisabled();

  await page.getByTestId("review-checklist").getByRole("checkbox").check();
  await expect(page.getByTestId("approve-button")).toBeEnabled();
  await page.getByTestId("approve-button").click();
  await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "APPROVED");
});
