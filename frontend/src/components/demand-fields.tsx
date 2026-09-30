"use client";

import Select from "@/components/ui/select";
import CalendarDates from "@/components/ui/calendar-dates";

type Obj = Record<string, unknown>;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="wb-field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}
function Zones({
  selected,
  zones,
  onChange,
}: {
  selected: string[];
  zones: string[];
  onChange: (ids: string[]) => void;
}) {
  return (
    <fieldset className="demand-zones">
      <legend>Зоны с датированным спросом</legend>
      {zones.map((id) => (
        <label key={id}>
          <input
            type="checkbox"
            checked={selected.includes(id)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...selected, id]
                  : selected.filter((item) => item !== id),
              )
            }
          />
          {id}
        </label>
      ))}
    </fieldset>
  );
}
export function MobilityFields({
  value,
  onChange,
  zones,
}: {
  value: string;
  onChange: (value: string) => void;
  zones: string[];
}) {
  let input: Obj;
  try {
    input = JSON.parse(value);
  } catch {
    return (
      <p className="wb-help">Исправьте JSON для работы с полями маршрутов.</p>
    );
  }
  const chosen = Array.isArray(input.replace_zone_ids)
    ? (input.replace_zone_ids as string[])
    : [];
  const update = (key: string, next: unknown) =>
    onChange(pretty({ ...input, [key]: next }));
  return (
    <div className="demand-fields">
      <h3>Покрытие и происхождение</h3>
      <div className="wb-fields">
        <Field
          label="Часовой пояс IANA"
          value={String(input.time_zone || "")}
          onChange={(next) => update("time_zone", next)}
        />
        <CalendarDates dates={Array.isArray(input.covered_dates) ? input.covered_dates as string[] : []} onChange={next => update("covered_dates", next)} />
        <Field
          label="Источник маршрутов"
          value={String(input.source || "")}
          onChange={(next) => update("source", next)}
        />
        <div className="wb-field">
          <span>Заявленное происхождение</span>
          <Select
            label="Заявленное происхождение"
            value={String(input.source_kind || "assumed")}
            onValueChange={(value) => update("source_kind", value)}
            options={[
              { value: "assumed", label: "Сценарное допущение" },
              { value: "observed", label: "Заявлено как наблюдение" },
            ]}
          />
        </div>
      </div>
      <Zones
        selected={chosen}
        zones={zones}
        onChange={(ids) => update("replace_zone_ids", ids)}
      />
      <p className="wb-help">
        Для каждой машины укажите сегмент, батарею, заряд, расход, вес и
        чередующиеся поездки/стоянки в JSON ниже. Отсутствующие дни и зоны не
        заполняются автоматически.
      </p>
    </div>
  );
}
export function DatedFields({
  value,
  onChange,
  zones,
}: {
  value: string;
  onChange: (value: string) => void;
  zones: string[];
}) {
  let input: Obj;
  try {
    input = JSON.parse(value);
  } catch {
    return <p className="wb-help">Исправьте JSON для работы с календарём.</p>;
  }
  const calendar = (input.service_calendar || {}) as Obj;
  const chosen = Array.isArray(calendar.request_zone_ids)
    ? (calendar.request_zone_ids as string[])
    : [];
  const updateCalendar = (key: string, next: unknown) =>
    onChange(
      pretty({
        ...input,
        service_calendar: {
          ...calendar,
          schema_version: "service-calendar-v1",
          annualization_basis: "assumed_repeat",
          [key]: next,
        },
      }),
    );
  return (
    <div className="demand-fields">
      <h3>Календарь обслуживания</h3>
      <div className="wb-fields">
        <Field
          label="Часовой пояс IANA"
          value={String(calendar.time_zone || "")}
          onChange={(next) => updateCalendar("time_zone", next)}
        />
        <CalendarDates dates={Array.isArray(calendar.covered_dates) ? calendar.covered_dates as string[] : []} onChange={next => updateCalendar("covered_dates", next)} />
        <label className="wb-field">
          <span>Множитель годовой экстраполяции · предположение</span>
          <input
            type="number"
            min="0.0001"
            step="any"
            value={
              calendar.annualization_factor === undefined
                ? ""
                : String(calendar.annualization_factor)
            }
            onChange={(event) =>
              updateCalendar(
                "annualization_factor",
                event.target.value ? Number(event.target.value) : undefined,
              )
            }
          />
        </label>
      </div>
      <Zones
        selected={chosen}
        zones={zones}
        onChange={(ids) =>
          onChange(
            pretty({
              ...input,
              service_calendar: {
                ...calendar,
                schema_version: "service-calendar-v1",
                annualization_basis: "assumed_repeat",
                request_zone_ids: ids,
                legacy_profile_zone_ids: zones.filter(
                  (id) => !ids.includes(id),
                ),
              },
            }),
          )
        }
      />
      <p className="wb-help">
        Остальные зоны явно остаются на повторяемом 24-часовом профиле. Заявки и
        окна прибытия/дедлайна заполните в JSON ниже.
      </p>
    </div>
  );
}
