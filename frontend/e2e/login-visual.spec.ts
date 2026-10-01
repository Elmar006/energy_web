import { expect, test } from "@playwright/test";

test("вход сохраняет компоновку, доступный фокус и ошибку на телефоне и десктопе", async ({ page }) => {
  await page.route("**/api/session", route => route.fulfill({
    status: route.request().method() === "POST" ? 401 : 200,
    json: route.request().method() === "POST" ? { error: "Неверный пароль" } : { signed_in: false },
  }));
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    const password = page.getByLabel("Пароль доступа", { exact: true });
    const submit = page.getByRole("button", { name: "Войти" });
    await expect(password).toBeInViewport();
    await expect(submit).toBeInViewport();
    await password.focus();
    expect(await password.evaluate(element => parseFloat(getComputedStyle(element).outlineWidth))).toBeGreaterThanOrEqual(2);
    await password.fill("invalid-test-password");
    await password.press("Tab");
    await expect(submit).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#password-error")).toBeVisible();
    await expect(password).toHaveAttribute("aria-invalid", "true");
    await expect(password).toHaveAttribute("aria-describedby", "password-error");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
