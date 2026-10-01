import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

test("локальные шрифты загружаются и разделяют заголовки и поля", async ({ page }) => {
  await page.route("**/api/session", route => route.fulfill({ json: { signed_in: true } }));
  await page.route("**/api/scenarios", route => route.fulfill({ json: [] }));
  const externalFontRequests: string[] = [];
  page.on("request", request => {
    if (request.resourceType() === "font" && new URL(request.url()).origin !== new URL(page.url()).origin) externalFontRequests.push(request.url());
  });
  await page.goto("/data/scenario");
  await expect(page.getByRole("heading", { name: "Данные", exact: true })).toBeVisible();
  await expect(page).toHaveTitle("Энергоконтур — планирование зарядной инфраструктуры");
  await expect(page.locator(".brand strong")).toHaveText("Энергоконтур");
  const logo = page.locator(".brand img");
  await expect(logo).toHaveAttribute("src", "/brand-logo.png");
  await expect.poll(() => logo.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "/brand-logo.png");
  const artwork = await page.request.get("/brand-logo.png");
  expect(artwork.ok()).toBe(true);
  const sha256 = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
  expect(sha256(await artwork.body())).toBe(sha256(readFileSync("public/brand-logo.png")));
  const fonts = await page.evaluate(async () => {
    await document.fonts.ready;
    const normalize = (family: string) => family.split(",")[0].trim().replaceAll('"', "").replaceAll("'", "");
    const body = normalize(getComputedStyle(document.body).fontFamily);
    const heading = normalize(getComputedStyle(document.querySelector("h1")!).fontFamily);
    const field = normalize(getComputedStyle(document.querySelector("input")!).fontFamily);
    const loaded = [...document.fonts].filter(face => face.status === "loaded").map(face => normalize(face.family));
    const sample = "Спрос Ёмкость кВт·ч ₽ 0123456789";
    return { body, heading, field, loaded, bodyReady: document.fonts.check(`400 14px "${body}"`, sample), headingReady: document.fonts.check(`600 36px "${heading}"`, sample) };
  });
  expect(fonts.heading).not.toBe(fonts.body);
  expect(fonts.field).toBe(fonts.body);
  expect(fonts.loaded).toContain(fonts.body);
  expect(fonts.loaded).toContain(fonts.heading);
  expect(fonts.bodyReady && fonts.headingReady).toBe(true);
  expect(externalFontRequests).toEqual([]);
});
