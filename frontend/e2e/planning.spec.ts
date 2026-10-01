import { expect, test } from "@playwright/test";
import { resolve } from "node:path";
import { readFileSync } from "node:fs";

test("карта 2ГИС загружает сценарные маркеры и поддерживает управление масштабом", async ({ page }) => {
  await page.route("**/api/maps/config", (route) => route.fulfill({
    contentType: "application/json", body: JSON.stringify({ configured: true, apiKey: "mapgl-test-key" }),
  }));
  await page.route("https://mapgl.2gis.com/api/js", (route) => route.fulfill({
    contentType: "application/javascript",
    body: `window.mapgl = {
      Map: class {
        constructor(container, options) {
          this.container = container; this.zoom = options.zoom;
          window.__mapglTest = { key: options.key, center: options.center, markers: [], zooms: [], fitted: false };
        }
        on() {}
        fitBounds() { window.__mapglTest.fitted = true; }
        getZoom() { return this.zoom; }
        setZoom(value) { this.zoom = value; window.__mapglTest.zooms.push(value); }
        setCenter(value) { window.__mapglTest.center = value; }
        destroy() { this.container.replaceChildren(); }
      },
      HtmlMarker: class {
        constructor(map, options) {
          map.container.appendChild(options.html);
          window.__mapglTest.markers.push(options.coordinates);
        }
      }
    };`,
  }));
  await page.goto("/");
  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(process.env.APP_ACCESS_PASSWORD ?? process.env.APP_DEMO_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти" }).click();

  await expect(page.getByRole("heading", { name: "Данные не загружены" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Рассчитать план" })).toBeDisabled();
  await page.getByText("Импорт готового сценария", { exact: true }).click();
  await page.locator("#scenario-file").setInputFiles(resolve(__dirname, "../../examples/demo.json"));
  await expect(page.locator("#workspace-scenario")).toHaveText("demo");
  await expect(page.getByText("2ГИС", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /зона спроса/ }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /кандидат/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Приблизить карту" }).click();
  const state = await page.evaluate(() => (window as typeof window & {
    __mapglTest: { key: string; markers: number[][]; zooms: number[]; fitted: boolean };
  }).__mapglTest);
  expect(state.key).toBe("mapgl-test-key");
  expect(state.markers.length).toBeGreaterThan(0);
  expect(state.fitted).toBe(true);
  expect(state.zooms).toEqual([13]);
});

test("мобильный сценарий доступен от входа до результата и выхода", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(process.env.APP_ACCESS_PASSWORD ?? process.env.APP_DEMO_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Планирование" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Выйти из рабочего пространства" })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Данные не загружены" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Рассчитать план" })).toBeDisabled();
  await page.getByText("Импорт готового сценария", { exact: true }).click();
  await page.locator("#scenario-file").setInputFiles(resolve(__dirname, "../../examples/demo.json"));
  await expect(page.locator("#workspace-scenario")).toHaveText("demo");
  await expect(page.getByRole("group", { name: "Карта территории сценария" })).toBeVisible();
  const mapConfig = await page.request.get("/api/maps/config");
  if (!(await mapConfig.json()).configured) {
    await expect(page.getByText("Карта ожидает подключения")).toBeVisible();
  } else {
    await expect(page.getByText("Открываем карту территории")).toHaveCount(0, { timeout: 16_000 });
  }
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 320, height: 720 });
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.getByRole("button", { name: "Рассчитать план" }).click();
  await expect(page.getByText("Расчёт завершён")).toBeVisible({ timeout: 150_000 });
  await expect(page.getByRole("button", { name: "Развернуть", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Рассчитать план", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Развернуть", exact: true }).click();
  await expect(page.getByRole("button", { name: "Рассчитать план", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Свернуть", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Этапы строительства" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Устойчивость к росту спроса" })).toBeVisible();
  await page.getByRole("tab", { name: "Сравнение", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Основной план и альтернативы" })).toBeVisible();
  await page.getByRole("tab", { name: "Данные и протокол", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Качество входа" })).toBeVisible();
  await page.getByRole("tab", { name: "Энергетика", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Энергетический аудит", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Эксплуатация", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Работа сети по дням" })).toBeVisible();
  await page.getByRole("tab", { name: "Данные и протокол", exact: true }).click();
  await expect(page.getByText("Спрос задан предположениями, а не измерен.")).toBeVisible();
  await page.getByRole("tab", { name: "Сравнение", exact: true }).click();
  await expect(page.getByRole("region", { name: "Сравнение планов" }).getByRole("table")).toBeVisible();
  await page.getByRole("tab", { name: "Энергетика", exact: true }).click();
  await expect(page.getByRole("region", { name: "Энергетический аудит по площадкам" }).getByRole("table")).toBeVisible();
  for (const width of [1440, 1280, 1024, 968, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of ["Сводка", "Территория", "Эксплуатация", "Энергетика", "Экономика", "Сравнение", "Данные и протокол"]) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), { message: `${tab}: overflow ${width}` }).toBe(true);
    }
  }
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт JSON" }).click();
  const file = await download;
  const exported = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(exported.schema_version).toBe("workspace-export-v1");
  expect(exported.run.id).toBeTruthy();
  expect(exported.result.optimization.selected.length).toBeGreaterThan(0);

  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await page.getByRole("button", { name: "Выйти из рабочего пространства" }).click();
  await expect(page.getByRole("textbox", { name: "Пароль доступа" })).toBeVisible();
});

test("пользовательский JSON загружается, проверяется и рассчитывается", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(process.env.APP_ACCESS_PASSWORD ?? process.env.APP_DEMO_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByText("Импорт готового сценария", { exact: true }).click();
  await page.locator("#scenario-file").setInputFiles(resolve(__dirname, "../../examples/import_sample.json"));
  await expect(page.locator("#workspace-scenario")).toHaveText("import_sample");
  await expect(page.locator(".source-quality")).toContainText("3 предположенных");
  await expect(page.getByText("1 кандидат")).toBeVisible();
  await page.getByRole("button", { name: "Рассчитать план" }).click();
  await expect(page.getByText("Расчёт завершён")).toBeVisible({ timeout: 150_000 });
  await expect(page.getByRole("listitem").getByText("Тестовая площадка · Казань")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("listitem").getByText("Тестовая площадка · Казань")).toBeVisible({ timeout: 30_000 });
});

test("закреплённый конкурсный кейс проходит от загрузки до проверяемого экрана", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(process.env.APP_ACCESS_PASSWORD ?? process.env.APP_DEMO_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByText("Импорт готового сценария", { exact: true }).click();
  await page.locator("#scenario-file").setInputFiles(resolve(__dirname, "../../examples/commission_monaco.json"));
  await expect(page.locator("#workspace-scenario")).toHaveText("commission_monaco");
  await page.getByRole("button", { name: "Рассчитать план" }).click();
  await expect(page.getByText("Расчёт завершён")).toBeVisible({ timeout: 150_000 });
  await page.getByRole("tab", { name: "Сравнение", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Основной план и альтернативы" })).toBeVisible();
  await expect(page.getByRole("row", { name: /Порог 50%/ })).toBeVisible();
  await page.getByRole("tab", { name: "Энергетика", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Энергетический аудит", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Эксплуатация", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Работа сети по дням" })).toBeVisible();
  await page.getByRole("tab", { name: "Данные и протокол", exact: true }).click();
  await expect(page.getByText("Спрос задан предположениями, а не измерен.")).toBeVisible();
  await expect.poll(async () => page.locator("header img").evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (process.env.ENERGY_SCREENSHOT) {
    await page.screenshot({ path: process.env.ENERGY_SCREENSHOT, fullPage: true });
    await page.getByRole("tab", { name: "Сравнение", exact: true }).click();
    await page.getByRole("heading", { name: "Основной план и альтернативы" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: process.env.ENERGY_SCREENSHOT.replace(/\.png$/, "-detail.png") });
  }
});

test("ограничение CVaR видно в результате, а несовместимые условия не выдаются за план", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(process.env.APP_ACCESS_PASSWORD ?? process.env.APP_DEMO_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти" }).click();
  const spec = JSON.parse(readFileSync(resolve(__dirname, "../../examples/import_sample.json"), "utf8"));
  spec.id = "e2e-city-cvar";
  spec.scenarios = [
    { id: "base", demand_multiplier: [1], probability: 0.9 },
    { id: "growth", demand_multiplier: [2], probability: 0.1 },
  ];
  spec.parameters.risk = "expected_cvar";
  spec.parameters.cvar_alpha = 0.9;
  spec.parameters.max_cvar_unmet_kwh = 0;
  await page.getByText("Импорт готового сценария", { exact: true }).click();
  await page.locator("#scenario-file").setInputFiles({ name: "cvar-test.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(spec)) });
  await expect(page.locator("#workspace-scenario")).toHaveText("cvar-test");
  await page.getByRole("button", { name: "Рассчитать план" }).click();
  await expect(page.getByText("Расчёт завершён")).toBeVisible({ timeout: 150_000 });
  await expect(page.getByText("CVaR · худшие 10% вероятности")).toBeVisible();
  await expect(page.getByText(/Допустимый предел: 0 кВт·ч/)).toBeVisible();

  spec.id = "e2e-city-cvar-infeasible";
  spec.grid_nodes[0].headroom_kw = Array(24).fill(0);
  await page.locator("#scenario-file").setInputFiles({ name: "cvar-impossible.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(spec)) });
  await expect(page.locator("#workspace-scenario")).toHaveText("cvar-impossible");
  await page.getByRole("button", { name: "Рассчитать план" }).click();
  await expect(page.getByRole("heading", { name: "Ограничения несовместимы" })).toBeVisible({ timeout: 150_000 });
  await expect(page.getByText("Расчёт завершён")).toHaveCount(0);
});
