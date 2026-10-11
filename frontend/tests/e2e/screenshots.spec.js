// Not a test: captures screenshots for docs/build-log (runs only when SCREENSHOT_DIR is set).
//   SCREENSHOT_DIR=/work/docs/screenshots SCREENSHOT_NAME=dev BASE_URL=... npx playwright test screenshots
const { test } = require("@playwright/test");

test("screenshot", async ({ page }) => {
  test.skip(!process.env.SCREENSHOT_DIR, "SCREENSHOT_DIR not set");
  await page.goto("/");
  await page.locator("#options button[data-option]").first().waitFor();
  await page.waitForTimeout(3500);    // let every card poll at least once
  await page.screenshot({ path: `${process.env.SCREENSHOT_DIR}/${process.env.SCREENSHOT_NAME || "page"}.png`,
                          fullPage: true });
});
