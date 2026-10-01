import { makeDemo } from "./fixtures/demo";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", route => route.fulfill({ json: { signed_in: true } }));
  await page.route("**/api/scenarios", route => route.fulfill({ json: [] }));
  await page.route("**/api/maps/config", route => route.fulfill({ json: { configured: false } }));
  await page.route("**/api/workbench/datasets", route => route.fulfill({ json: [] }));
});

for (const width of [1440, 1280, 1024, 968, 390, 320]) {
  test(`рабочие страницы не расширяют документ: ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/plan", "/data/scenario", "/data/csv/sessions", "/data/csv/grid", "/data/geo", "/data/dated", "/mobility", "/models/fleet", "/models/corridor"]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("combobox", { name: "Источник расчёта" })).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), { message: `${path} overflow at ${width}` }).toBe(true);
      if (path !== "/plan") await expect(page.getByRole("button", { name: "Рассчитать план", exact: true })).toHaveCount(0);
    }
  });
}

test("вкладки доступны с клавиатуры, реестр работает без картографического провайдера", async ({ page }) => {
  const id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
  await page.route("**/api/scenarios/" + id, route => route.fulfill({ json: { id, name: "Synthetic test fixture", spec: makeDemo("city", 10000000, 100) } }));
  await page.goto("/plan?scenario=" + id);
  await page.getByRole("tab", { name: "Сводка", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Территория", exact: true })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Территория", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Площадка B · Центр", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Свойства площадки" })).toContainText("Площадка B · Центр");
  await page.getByRole("textbox", { name: "Поиск площадки" }).fill("нет такой площадки");
  await expect(page.getByText("Площадки не найдены. Измените запрос.")).toBeVisible();
  await page.getByRole("tab", { name: "Территория", exact: true }).focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Данные и протокол", exact: true })).toBeFocused();
  await expect(page.getByRole("heading", { name: "Сначала рассчитайте план" })).toBeVisible();
});

test("коридор: табличный ввод отправляет значения и показывает предметный результат", async ({ page }) => {
  let request: Record<string, unknown> | undefined;
  await page.route("**/api/workbench/corridors/check", async route => {
    request = route.request().postDataJSON();
    await route.fulfill({ json: { reachable: true, farthest_reachable_km: 100, stops: ["station-1"], legs: [{ from: "start", to: "station-1", distance_km: 50, arrival_soc: 0.5 }], station_failure_impacts: { "station-1": { reachable: false, replacement_stops: [] } }, assumptions: ["no station queue or opening hours"] } });
  });
  await page.goto("/models/corridor");
  await page.getByRole("spinbutton", { name: "Длина маршрута · км" }).fill("100");
  await page.getByRole("spinbutton", { name: "Полезная ёмкость · кВт·ч" }).fill("60");
  await page.getByRole("spinbutton", { name: "Начальный заряд · %" }).fill("80");
  await page.getByRole("spinbutton", { name: "Резерв заряда · %" }).fill("10");
  await page.getByRole("spinbutton", { name: "Расход · кВт·ч/км" }).fill("0.2");
  await page.getByRole("button", { name: "Добавить строку" }).click();
  await page.getByRole("textbox", { name: "Идентификатор, строка 1" }).fill("station-1");
  await page.getByRole("spinbutton", { name: "Расстояние от начала, км, строка 1" }).fill("50");
  await page.getByRole("button", { name: /Удалить строку 1/ }).click();
  await page.getByRole("button", { name: "Восстановить" }).click();
  await expect(page.getByRole("textbox", { name: "Идентификатор, строка 1" })).toHaveValue("station-1");
  await page.getByRole("button", { name: "Выполнить расчёт" }).click();
  await expect(page.getByRole("region", { name: "Результат модели", exact: true })).toContainText("Маршрут достижим");
  expect(request).toMatchObject({ route_km: 100, initial_soc: 0.8, reserve_soc: 0.1, stations: [{ id: "station-1", km: 50, available: true }] });
  await expect(page.getByRole("region", { name: "Отказы станций" })).toContainText("Недостижим");
});

test("CSV сообщает условие импорта до заполнения формы", async ({ page }) => {
  await page.goto("/data/csv/sessions");
  await expect(page.getByText("Сначала выберите сохранённый сценарий", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Создать сценарий", exact: true }).click();
  await expect(page).toHaveURL(/\/data\/scenario$/);
});

test("ошибка нового источника не подменяется предыдущим сценарием", async ({ page }) => {
  const valid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", missing = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
  await page.route("**/api/scenarios/" + valid, route => route.fulfill({ json: { id: valid, name: "Previous input", spec: makeDemo("city", 10000000, 100) } }));
  await page.route("**/api/scenarios/" + missing, route => route.fulfill({ status: 404, json: { error: "not found" } }));
  await page.goto("/plan?scenario=" + valid);
  await expect(page.getByRole("button", { name: "Рассчитать план" })).toBeEnabled();
  await page.evaluate((id) => window.history.pushState({}, "", "/plan?scenario=" + id), missing);
  await expect(page.getByRole("alert").filter({ hasText: "Сценарий не удалось открыть" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Данные не загружены" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Рассчитать план" })).toBeDisabled();
  await expect(page.getByRole("combobox", { name: "Источник расчёта" })).toHaveText("Данные не выбраны");
});

test("календарь сохраняет даты и предупреждает о пропусках", async ({ page }) => {
  await page.goto("/data/dated");
  await page.getByLabel("Добавить дату", { exact: true }).fill("2027-01-01");
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await page.getByLabel("Добавить дату", { exact: true }).fill("2027-01-03");
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(page.getByText(/Между датами есть пропуски/)).toBeVisible();
  await page.getByText("Заявки и календарь · полный JSON", { exact: true }).click();
  const serialized = await page.getByRole("textbox", { name: "demand-dataset-v1 · service_calendar и charging_requests" }).inputValue();
  expect(JSON.parse(serialized).service_calendar.covered_dates).toEqual(["2027-01-01", "2027-01-03"]);
  await page.getByRole("button", { name: "Убрать дату 2027-01-03" }).click();
  await expect(page.getByText(/Между датами есть пропуски/)).toHaveCount(0);
});

test("парк: таблицы сохраняют связи и экспертные поля, редактирование снимает старый результат", async ({ page }) => {
  let payload: Record<string, unknown> | undefined;
  await page.route("**/api/workbench/fleets/schedule", async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ json: { status: "optimal", peak_kw: 20, trip_ids_served: ["trip-1"], schedule: [{ bus_id: "bus-1", site_id: "depot", slot: 0, kw: 20 }], end_energy_kwh: { "bus-1": 60 } } });
  });
  await page.goto("/models/fleet");
  await page.getByText("Параметры JSON", { exact: true }).click();
  await page.getByRole("textbox", { name: "FleetSpec JSON" }).fill(JSON.stringify({
    horizon_slots: 8, slot_minutes: 15, efficiency: 0.95, solver_seconds: 30,
    buses: [{ id: "bus-1", battery_kwh: 100, initial_kwh: 60, minimum_kwh: 10, end_target_kwh: 60 }],
    sites: [{ id: "depot", ports: 2, charger_kw: 50, grid_kw: 80, grid_profile_kw: Array(8).fill(80) }],
    trips: [{ id: "trip-1", bus_id: "bus-1", start_slot: 2, end_slot: 4, energy_kwh: 10 }],
    windows: [{ bus_id: "bus-1", site_id: "depot", start_slot: 0, end_slot: 2 }],
  }));
  await page.getByRole("spinbutton", { name: "КПД зарядки · %" }).fill("90");
  await page.getByRole("spinbutton", { name: "Подключение, кВт, строка 1" }).fill("70");
  await expect(page.getByRole("combobox", { name: "Площадка, строка 1", exact: true })).toHaveValue("depot");
  await page.getByRole("button", { name: "Выполнить расчёт" }).click();
  await expect(page.getByRole("region", { name: "Расписание зарядки", exact: true })).toContainText("bus-1");
  expect(payload).toMatchObject({ efficiency: 0.9, sites: [{ id: "depot", grid_kw: 70, grid_profile_kw: Array(8).fill(80) }] });
  await page.getByRole("spinbutton", { name: "КПД зарядки · %" }).fill("95");
  await expect(page.getByRole("region", { name: "Результат модели", exact: true })).toHaveCount(0);
});

test("основные контрастные пары и клавиатурный фокус проходят проверку", async ({ page }) => {
  await page.goto("/models/corridor");
  const ratios = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const color = (name: string) => root.getPropertyValue(name).trim();
    const luminance = (hex: string) => {
      const full = hex.length === 4 ? hex.slice(1).split("").map(c => c + c).join("") : hex.slice(1);
      const rgb = [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16) / 255).map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
      return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    };
    const contrast = (a: string, b: string) => {
      const x = luminance(color(a)), y = luminance(color(b));
      return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    };
    return { body: contrast("--text", "--page"), muted: contrast("--muted", "--surface-raised"), rail: contrast("--rail-muted", "--accent"), field: contrast("--control-border", "--surface") };
  });
  expect(ratios.body).toBeGreaterThanOrEqual(4.5);
  expect(ratios.muted).toBeGreaterThanOrEqual(4.5);
  expect(ratios.rail).toBeGreaterThanOrEqual(4.5);
  expect(ratios.field).toBeGreaterThanOrEqual(3);
  const source = page.getByRole("combobox", { name: "Источник расчёта" });
  await source.focus();
  const outline = await source.evaluate(el => getComputedStyle(el).outlineWidth);
  expect(parseFloat(outline)).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect(source).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(source).toBeFocused();
  await expect(source).toHaveAttribute("aria-expanded", "false");
});

test("мобильная навигация показывает все четыре раздела без скрытой прокрутки", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto("/plan");
  const navigation = page.getByRole("navigation", { name: "Разделы рабочего пространства" });
  for (const name of ["Планирование", "Данные и версии", "Маршруты", "Отдельные модели"]) {
    const link = navigation.getByRole("link", { name, exact: true });
    await expect(link).toBeInViewport();
    const bounds = await link.boundingBox();
    expect(bounds!.width).toBeGreaterThanOrEqual(24);
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
  }
  await navigation.getByRole("link", { name: "Отдельные модели", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/models\/corridor$/);
  await expect(navigation.getByRole("link", { name: "Отдельные модели", exact: true })).toHaveAttribute("aria-current", "page");
});

test("пустой экран ведёт к загрузке входа до недоступных настроек расчёта", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/plan");
  const prepare = page.getByRole("link", { name: "Добавить данные" });
  const run = page.getByRole("button", { name: "Рассчитать план", exact: true });
  await expect(prepare).toBeInViewport();
  await expect(run).toBeDisabled();
  const prepareBounds = await prepare.boundingBox(), runBounds = await run.boundingBox();
  expect(prepareBounds!.y).toBeLessThan(runBounds!.y);
  expect(prepareBounds!.height).toBeGreaterThanOrEqual(44);
  await prepare.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/data\/scenario$/);
  await expect(page.getByRole("textbox", { name: "Имя новой версии" })).toBeVisible();
});
