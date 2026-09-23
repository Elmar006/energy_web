import { expect, test } from "@playwright/test";

test("мобильный сценарий доступен от входа до результата и выхода", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(process.env.APP_DEMO_PASSWORD ?? "demo-local-password");
  await page.getByRole("button", { name: "Открыть рабочее пространство" }).click();
  await expect(page.getByRole("heading", { name: "Развитие зарядной сети" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Выйти из рабочего пространства" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Карта пилотной территории" })).toBeVisible();
  if (!process.env.YANDEX_MAPS_API_KEY) {
    await expect(page.getByText("Карта ожидает подключения")).toBeVisible();
  }
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 320, height: 720 });
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.getByRole("radio", { name: /Для оператора/ }).check();
  await expect(page.getByRole("radio", { name: /Для оператора/ })).toBeChecked();
  await page.getByRole("radio", { name: /Для города/ }).check();
  await page.getByRole("slider", { name: /Инвестиционный бюджет/ }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("slider", { name: /Инвестиционный бюджет/ })).toHaveValue("11");

  await page.getByRole("button", { name: "Рассчитать план" }).click();
  await expect(page.getByText("Расчёт завершён")).toBeVisible({ timeout: 150_000 });
  await expect(page.getByRole("heading", { name: "Этапы строительства" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Устойчивость к росту спроса" })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await page.getByRole("button", { name: "Выйти из рабочего пространства" }).click();
  await expect(page.getByRole("textbox", { name: "Пароль доступа" })).toBeVisible();
});
