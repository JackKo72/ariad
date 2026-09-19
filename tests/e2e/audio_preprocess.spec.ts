import path from "node:path";
import { expect, test } from "@playwright/test";

const FIXTURE_WAV = path.join(__dirname, "fixtures", "upload_test.wav");

test.describe("Task 02 Phase B: audio standardization/denoise", () => {
  test("preprocessing produces a second, independently playable track", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("consent-checkbox").check();
    await page.getByTestId("create-encounter-button").click();
    await expect(page).toHaveURL(/\/encounters\/.+/);

    await page.getByTestId("input-method-audio").click();
    await page.getByTestId("audio-file-input").setInputFiles(FIXTURE_WAV);
    await expect(page.getByTestId("audio-asset-info")).toBeVisible();

    await page.getByTestId("preprocess-mode-light-denoise").click();
    await page.getByTestId("preprocess-button").click();

    await expect(page.getByTestId("processed-audio-info")).toBeVisible();
    const originalSrc = await page.getByTestId("original-audio-player").getAttribute("src");
    const processedSrc = await page.getByTestId("processed-audio-player").getAttribute("src");
    expect(processedSrc).not.toBe(originalSrc);

    const response = await page.request.get(processedSrc!);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toBe("audio/wav");
  });
});
