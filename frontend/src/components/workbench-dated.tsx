"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight, Info } from "lucide-react";
import { DatedFields } from "@/components/demand-fields";
import { api, pretty, JsonEditor, type Obj } from "./workbench-shared";

export default function DatedSection() {
  const {
    section,
    spec,
    scenario,
    router,
    datedJson,
    busy,
    perform,
    jsonHeaders,
    setDatedJson,
    setMessage,
  } = useWorkbench();
  return (
    <>
      {section === "dated" && (
        <div className="wb-body">
          <p className="wb-note">
            <Info size={17} /> Календарь: 1–14 последовательных дней, явные зоны
            заявок и типового профиля. Экономика короткого периода
            масштабируется заданным annualization_factor.
          </p>
          <DatedFields
            value={datedJson}
            onChange={setDatedJson}
            zones={spec.zones.map((item) => item.id)}
          />
          <details className="wb-advanced">
            <summary>Заявки и календарь · полный JSON</summary>
            <JsonEditor
              label="demand-dataset-v1 · service_calendar и charging_requests"
              value={datedJson}
              setValue={setDatedJson}
              rows={22}
            />
          </details>
          <button
            className="primary-button"
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                const input = JSON.parse(datedJson);
                if (input.schema_version !== "demand-dataset-v1")
                  throw new Error("Нужен schema_version=demand-dataset-v1");
                const manifest = await api("artifacts/demand", {
                  method: "POST",
                  headers: jsonHeaders,
                  body: datedJson,
                });
                const next = { ...spec, demand_dataset: manifest } as Obj;
                delete next.service_calendar;
                delete next.charging_requests;
                sessionStorage.setItem(
                  "energy-planner:scenario-draft",
                  pretty(next),
                );
                router.push(
                  "/data/scenario" +
                    (scenario ? "?scenario=" + scenario.id : ""),
                );
                setMessage(
                  "Артефакт " +
                    manifest.artifact_id +
                    " добавлен в редактор. Сохраните новую версию.",
                );
              })
            }
          >
            Загрузить набор и открыть редактор <ArrowRight size={17} />
          </button>
        </div>
      )}
    </>
  );
}
