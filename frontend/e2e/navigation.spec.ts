import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ signed_in: true }),
    }),
  );
  await page.route("**/api/scenarios", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/maps/config", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ configured: false }),
    }),
  );
  await page.route("**/api/workbench/datasets", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
});

test("разделы и вложенные вкладки открываются по URL", async ({ page }) => {
  let sessionChecks = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/session") sessionChecks += 1;
  });
  await page.goto("/plan");
  await expect(
    page.getByRole("heading", { name: "Развитие зарядной сети" }),
  ).toBeVisible();
  await page.evaluate(() => {
    (window as typeof window & { workspaceDocumentMarker?: number }).workspaceDocumentMarker = 1;
  });
  await expect(page.getByRole("heading", { name: "Данные не загружены" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Рассчитать план" })).toBeDisabled();
  await page.getByRole("combobox", { name: "Источник расчёта" }).click();
  await expect(
    page.getByRole("listbox", { name: "Источник расчёта" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Источник расчёта" })
    .press("Escape");
  await expect(
    page.getByRole("listbox", { name: "Источник расчёта" }),
  ).toHaveCount(0);

  await page.getByRole("link", { name: "Данные и версии" }).click();
  await expect(page).toHaveURL(/\/data\/scenario$/);
  await page.getByRole("link", { name: "CSV сессий и сети" }).click();
  await expect(page).toHaveURL(/\/data\/csv\/sessions$/);
  await page.getByRole("link", { name: "Резерв сети" }).click();
  await expect(page).toHaveURL(/\/data\/csv\/grid$/);
  await page.getByRole("link", { name: "Геоданные" }).click();
  await expect(page).toHaveURL(/\/data\/geo$/);

  await page.getByRole("link", { name: "Отдельные модели" }).click();
  await expect(page).toHaveURL(/\/models\/corridor$/);
  await page.getByRole("link", { name: "Парк" }).click();
  await expect(page).toHaveURL(/\/models\/fleet$/);
  await expect(page.getByRole("slider", { name: /Инвестиционный бюджет/ })).toHaveCount(0);
  expect(
    await page.evaluate(
      () =>
        (window as typeof window & { workspaceDocumentMarker?: number })
          .workspaceDocumentMarker,
    ),
  ).toBe(1);

  await page.goBack();
  await expect(page).toHaveURL(/\/models\/corridor$/);
  await page.getByRole("link", { name: "Планирование", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Данные не загружены" })).toBeVisible();
  await page.goBack();
  expect(sessionChecks).toBe(1);
  await page.reload();
  await expect(page.getByRole("link", { name: "Коридор" })).toHaveAttribute(
    "class",
    /active/,
  );
});
