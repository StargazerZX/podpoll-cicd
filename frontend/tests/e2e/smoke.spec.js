// Smoke test: the page renders what the API says, voting works, and the CSP blocks nothing of ours.
// Environment-agnostic: expectations are read from the running API, so it works on dev/prod/ECS.
const { test, expect } = require("@playwright/test");

const COLOURS = { prod: "rgb(185, 28, 28)", staging: "rgb(194, 65, 12)", dev: "rgb(21, 128, 61)",
                  preview: "rgb(15, 118, 110)", default: "rgb(29, 78, 216)" };

test("PodPoll renders, reports its build, and counts a vote", async ({ page, request }) => {
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(e.message));

  const info = await (await request.get("/api/info")).json();
  const build = await (await request.get("/build.json")).json();

  await page.goto("/");
  await expect(page).toHaveTitle("PodPoll");

  // Environment badge comes from the API's answer, with the right colour.
  const badge = page.locator("#env");
  await expect(badge).toContainText(`: ${info.env}`);
  await expect(badge).toHaveCSS("background-color", COLOURS[info.env] || "rgb(126, 34, 206)");
  await expect(page.locator("#platform")).toHaveText(`on ${info.platform}`);

  // Theme follows the frontend's major version.
  const major = (/^v?(\d+)/.exec(build.version) || [])[1] || "";
  await expect(page.locator("body")).toHaveAttribute("data-major", String(Number(major) || major));

  // Card 6 shows both tiers' builds.
  await expect(page.locator("#build-fe td").first()).toHaveText(build.version);
  await expect(page.locator("#build-api td").first()).toHaveText(info.version);

  // Card 5 (RBAC) only on Kubernetes.
  await expect(page.locator("#card-rbac")).toBeVisible({ visible: info.platform === "kubernetes" });

  // Vote and watch the total go up.
  const total = page.locator("#total");
  await expect(total).toContainText("total votes:");
  const before = Number((await total.textContent()).match(/\d+/)[0]);
  await page.locator("#options button[data-option]").first().click();
  await expect(total).toContainText(`total votes: ${before + 1}`);

  // Nothing blocked by the Content-Security-Policy, no script errors.
  expect(problems, problems.join("\n")).toEqual([]);
});

test("security headers are present", async ({ request }) => {
  const res = await request.get("/");
  const h = res.headers();
  expect(h["content-security-policy"]).toContain("default-src 'self'");
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("no-referrer");
  expect(h["server"]).toBe("nginx");   // server_tokens off: no version number
});
