"use client";

import Select from "@/components/ui/select";

type Item = Record<string, unknown>;
type Spec = Item & {
  zones?: Item[];
  sites?: Item[];
  grid_nodes?: Item[];
  scenarios?: Item[];
  parameters?: Item;
  options?: Item[];
};
type Props = { value: string; onChange: (value: string) => void };
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
function numberList(value: unknown) {
  return Array.isArray(value) ? value.join(", ") : "";
}
function splitNumbers(value: string) {
  const parts = value
    .split(/[,\s]+/)
    .filter(Boolean)
    .map(Number);
  if (parts.some((item) => !Number.isFinite(item)))
    throw new Error("Список должен содержать только числа");
  return parts;
}

export default function ScenarioFields({ value, onChange }: Props) {
  let spec: Spec;
  try {
    spec = JSON.parse(value);
  } catch {
    return (
      <p className="wb-help">Исправьте JSON, чтобы открыть поля редактора.</p>
    );
  }
  function set(path: string[], next: unknown) {
    const copy = structuredClone(spec);
    let node: Item = copy;
    for (const key of path.slice(0, -1)) node = node[key] as Item;
    node[path.at(-1)!] = next;
    onChange(pretty(copy));
  }
  function remove(path: string[]) {
    const copy = structuredClone(spec);
    let node: Item = copy;
    for (const key of path.slice(0, -1)) node = node[key] as Item;
    delete node[path.at(-1)!];
    onChange(pretty(copy));
  }
  function input(
    label: string,
    path: string[],
    value: unknown,
    mode: "text" | "number" = "text",
  ) {
    return (
      <label className="wb-field" key={path.join(".")}>
        <span>{label}</span>
        <input
          type={mode}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(event) =>
            event.target.value === "" && mode === "number"
              ? remove(path)
              : set(
                  path,
                  mode === "number"
                    ? Number(event.target.value)
                    : event.target.value,
                )
          }
        />
      </label>
    );
  }
  function list(label: string, path: string[], value: unknown) {
    return (
      <label className="wb-field" key={path.join(".")}>
        <span>{label}</span>
        <input
          defaultValue={numberList(value)}
          onBlur={(event) => {
            try {
              set(path, splitNumbers(event.target.value));
            } catch {
              event.target.setCustomValidity("Введите числа через запятую");
              event.target.reportValidity();
            }
          }}
          onChange={(event) => event.target.setCustomValidity("")}
        />
      </label>
    );
  }
  function provenance(item: Item, path: string[]) {
    const current = (item.provenance || {}) as Item;
    return (
      <>
        <div className="wb-field">
          <span>Происхождение</span>
          <Select
            label="Происхождение"
            value={String(current.kind || "assumed")}
            onValueChange={(value) =>
              set([...path, "provenance"], { ...current, kind: value })
            }
            options={[
              { value: "assumed", label: "Допущение" },
              { value: "derived", label: "Вычислено" },
              { value: "observed", label: "Заявлено как наблюдение" },
            ]}
          />
        </div>
        <label className="wb-field">
          <span>Источник</span>
          <input
            value={String(current.source || "")}
            onChange={(event) =>
              set([...path, "provenance"], {
                ...current,
                source: event.target.value,
              })
            }
          />
        </label>
      </>
    );
  }
  return (
    <div className="guided-editor">
      <div className="guided-grid">
        <h3>Параметры и бюджет</h3>
        <div className="wb-fields">
          {input("ID расчётного входа", ["id"], spec.id)}
          <div className="wb-field">
            <span>Цель</span>
            <Select
              label="Цель"
              value={String(spec.parameters?.mode || "city")}
              onValueChange={(value) => set(["parameters", "mode"], value)}
              options={[
                { value: "city", label: "Город · обслуженная энергия" },
                { value: "operator", label: "Оператор · экономика" },
              ]}
            />
          </div>
          {input(
            "Общий бюджет, ₽",
            ["parameters", "total_budget_rub"],
            spec.parameters?.total_budget_rub,
            "number",
          )}
          {list(
            "Годовые бюджеты, ₽",
            ["parameters", "annual_budgets_rub"],
            spec.parameters?.annual_budgets_rub,
          )}
          {list("Годы", ["parameters", "years"], spec.parameters?.years)}
          {input(
            "Минимум обслуживания зон, доля",
            ["parameters", "minimum_zone_service"],
            spec.parameters?.minimum_zone_service,
            "number",
          )}
        </div>
      </div>
      <div className="guided-grid">
        <h3>Зоны спроса</h3>
        {spec.zones?.map((zone, index) => (
          <details key={String(zone.id)}>
            <summary>
              {String(zone.name || zone.id)} · {String(zone.group || "segment")}
            </summary>
            <div className="wb-fields">
              {input("Название", ["zones", String(index), "name"], zone.name)}
              {input(
                "Средняя сессия, кВт·ч",
                ["zones", String(index), "mean_session_kwh"],
                zone.mean_session_kwh,
                "number",
              )}
              {input(
                "Допустимое время пути, мин",
                ["zones", String(index), "max_travel_minutes"],
                zone.max_travel_minutes,
                "number",
              )}
              {input("Сегмент", ["zones", String(index), "group"], zone.group)}
              {provenance(zone, ["zones", String(index)])}
            </div>
            {list(
              "Спрос по 24 часам, кВт·ч",
              ["zones", String(index), "hourly_kwh"],
              zone.hourly_kwh,
            )}
          </details>
        ))}
      </div>
      <div className="guided-grid">
        <h3>Площадки</h3>
        {spec.sites?.map((site, index) => (
          <details key={String(site.id)}>
            <summary>{String(site.name || site.id)}</summary>
            <div className="wb-fields">
              {input("Название", ["sites", String(index), "name"], site.name)}
              {input(
                "Широта",
                ["sites", String(index), "latitude"],
                site.latitude,
                "number",
              )}
              {input(
                "Долгота",
                ["sites", String(index), "longitude"],
                site.longitude,
                "number",
              )}
              {input(
                "ID узла сети",
                ["sites", String(index), "grid_node_id"],
                site.grid_node_id,
              )}
              {provenance(site, ["sites", String(index)])}
            </div>
            <p className="wb-help">
              Варианты оборудования и ограничения площадки доступны в полном
              JSON ниже.
            </p>
          </details>
        ))}
      </div>
      <div className="guided-grid">
        <h3>Узлы сети</h3>
        {spec.grid_nodes?.map((node, index) => (
          <details key={String(node.id)}>
            <summary>{String(node.id)}</summary>
            <div className="wb-fields">
              {input(
                "Усиление, кВт",
                ["grid_nodes", String(index), "upgrade_kw"],
                node.upgrade_kw,
                "number",
              )}
              {input(
                "CAPEX усиления, ₽",
                ["grid_nodes", String(index), "upgrade_capex_rub"],
                node.upgrade_capex_rub,
                "number",
              )}
              {provenance(node, ["grid_nodes", String(index)])}
            </div>
            {list(
              "Доступный резерв по 24 часам, кВт",
              ["grid_nodes", String(index), "headroom_kw"],
              node.headroom_kw,
            )}
          </details>
        ))}
      </div>
      <div className="guided-grid">
        <h3>Сценарии неопределённости</h3>
        {spec.scenarios?.map((item, index) => (
          <details key={String(item.id)}>
            <summary>{String(item.id)}</summary>
            <div className="wb-fields">
              {list(
                "Множитель спроса по годам",
                ["scenarios", String(index), "demand_multiplier"],
                item.demand_multiplier,
              )}
              {input(
                "Множитель тарифа",
                ["scenarios", String(index), "tariff_multiplier"],
                item.tariff_multiplier,
                "number",
              )}
              {input(
                "Вероятность · только если обоснована",
                ["scenarios", String(index), "probability"],
                item.probability,
                "number",
              )}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
