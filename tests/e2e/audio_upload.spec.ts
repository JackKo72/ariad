import path from "node:path";
import { expect, test } from "@playwright/test";

const FIXTURE_WAV = path.join(__dirname, "fixtures", "upload_test.wav");

test.describe("Task 02 Phase A: audio upload", () => {
  test("selecting a local audio file uploads it and plays the original", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();
    await expect(page).toHaveURL(/\/encounters\/.+/);
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "DRAFT");

    await page.getByTestId("input-method-audio").click();
    await page.getByTestId("audio-file-input").setInputFiles(FIXTURE_WAV);

    await expect(page.getByTestId("audio-asset-info")).toBeVisible();
    const player = page.getByTestId("original-audio-player");
    await expect(player).toBeVisible();
    const src = await player.getAttribute("src");
    expect(src).toContain("/audio/");
    expect(src).toContain("/stream");

    // The stream endpoint must actually serve playable bytes.
    const response = await page.request.get(src!);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("audio/");
  });

  test("attempting transcription without a real ASR provider shows ASR_NOT_CONFIGURED and manual fallback still works (Phase D)", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();
    await expect(page).toHaveURL(/\/encounters\/.+/);

    await page.getByTestId("input-method-audio").click();
    await page.getByTestId("audio-file-input").setInputFiles(FIXTURE_WAV);
    await expect(page.getByTestId("audio-asset-info")).toBeVisible();

    await page.getByTestId("transcribe-button").click();
    await expect(page.getByText(/ASR_NOT_CONFIGURED/)).toBeVisible();

    await page.getByTestId("input-method-transcript").click();
    await page.getByTestId("transcript-input").fill("의사: 안녕하세요.\n환자: 안녕하세요.");
    await page.getByTestId("submit-input-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "SUBMITTED");
  });

  test("switching back to transcript input still works (Task 01 regression)", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();
    await expect(page).toHaveURL(/\/encounters\/.+/);

    await page.getByTestId("input-method-audio").click();
    await expect(page.getByTestId("audio-file-input")).toBeVisible();

    await page.getByTestId("input-method-transcript").click();
    await page.getByTestId("transcript-input").fill("의사: 안녕하세요.\n환자: 안녕하세요.");
    await page.getByTestId("submit-input-button").click();
    await expect(page.getByTestId("status-badge")).toHaveAttribute("data-status", "SUBMITTED");
  });
});
