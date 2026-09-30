import { test, expect } from "@playwright/test";

const password = process.env.APP_ACCESS_PASSWORD ?? process.env.APP_DEMO_PASSWORD ?? "";

test("API отклоняет чужой Origin и запрос без Origin до изменения данных", async ({ request, baseURL }) => {
  const origins: Record<string, string>[] = [{ Origin: "https://untrusted.example" }, {}];
  for (const headers of origins) {
    const response = await request.post("/api/session", { headers, data: { password } });
    expect(response.status()).toBe(403);
  }
  const response = await request.post("/api/session", { headers: { Origin: baseURL! }, data: { password } });
  expect(response.status()).toBe(200);
  const cookie = response.headers()["set-cookie"];
  expect(cookie).toContain("HttpOnly");
  expect(cookie).toContain("SameSite=strict");
});

test("без сценария нет автоматически созданных площадок и расчётов", async ({ page, baseURL }) => {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Пароль доступа" }).fill(password);
  await page.getByRole("button", { name: "Открыть рабочее пространство" }).click();
  await expect(page.getByRole("heading", { name: "Данные не загружены" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Рассчитать план" })).toBeDisabled();
  await expect(page.getByText("3 узла", { exact: true })).toHaveCount(0);
  await expect(page.getByText("4 кандидата", { exact: true })).toHaveCount(0);
  const before = await (await page.request.get("/api/scenarios")).json();
  for (const data of [{ mode: "city", budget: 10000000, demand: 100 }, {}, { scenario_id: "------------------------------------" }]) {
    const response = await page.request.post("/api/runs", { data, headers: { Origin: baseURL! } });
    expect(response.status()).toBe(422);
  }
  const after = await (await page.request.get("/api/scenarios")).json();
  // Compare ids: a concurrent browser test may legitimately import another scenario.
  expect(after.filter((item: { id: string; name: string }) => !before.some((old: { id: string }) => old.id === item.id)).every((item: {name:string}) => !item.name.startsWith("Демо ·"))).toBe(true);
  for (const data of [null, [], { name: "invalid", spec: [] }]) {
    const response = await page.request.post("/api/scenarios", { headers: { Origin: baseURL!, "Content-Type": "application/json" }, data: JSON.stringify(data) });
    expect(response.status()).toBe(422);
  }
});

test("ограничение тела запроса и заголовки безопасности действуют на работающем BFF", async ({ request, baseURL }) => {
  const response = await request.post("/api/session", { headers: { Origin: baseURL! }, data: "x".repeat(5000) });
  expect(response.status()).toBe(413);
  const page = await request.get("/login");
  expect(page.headers()["x-frame-options"]).toBe("DENY");
  expect(page.headers()["x-content-type-options"]).toBe("nosniff");
  expect(page.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(page.headers()["x-powered-by"]).toBeUndefined();
});
