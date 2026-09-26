"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight, Info } from "lucide-react";
import ModelFields from "@/components/model-fields";
import Link from "next/link";
import { api, pretty, JsonEditor } from "./workbench-shared";

export default function ModelsSection() {
  const {
    view,
    model,
    scenario,
    modelJson,
    modelResult,
    busy,
    perform,
    jsonHeaders,
    setModelJson,
    setModelResult,
  } = useWorkbench();
  return (
    <>
      {view === "models" && (
        <div className="wb-body">
          <p className="wb-note">
            <Info size={17} /> Модели коридора и парка работают отдельно от
            городского плана и требуют собственных входов. Общие посты и бюджет
            между ними не распределяются.
          </p>
          <div className="wb-segment">
            <Link
              href={
                "/models/corridor" +
                (scenario ? "?scenario=" + scenario.id : "")
              }
              className={model === "corridors/check" ? "active" : ""}
            >
              Коридор
            </Link>
            <Link
              href={
                "/models/fleet" + (scenario ? "?scenario=" + scenario.id : "")
              }
              className={model === "fleets/schedule" ? "active" : ""}
            >
              Парк
            </Link>
          </div>
          <p className="wb-help">
            {model === "corridors/check"
              ? "Передайте CorridorSpec с маршрутом, энергетикой машины и станциями."
              : "Передайте FleetSpec с назначенными рейсами, окнами зарядки, батареями и лимитами депо."}
          </p>
          <ModelFields
            model={model}
            value={modelJson}
            onChange={setModelJson}
          />
          <details className="wb-advanced">
            <summary>Полный контракт модели · JSON</summary>
            <JsonEditor
              label={
                model === "corridors/check"
                  ? "CorridorSpec JSON"
                  : "FleetSpec JSON"
              }
              value={modelJson}
              setValue={setModelJson}
              rows={22}
            />
          </details>
          <button
            className="primary-button"
            disabled={busy}
            onClick={() =>
              void perform(async () =>
                setModelResult(
                  await api(model, {
                    method: "POST",
                    headers: jsonHeaders,
                    body: pretty(JSON.parse(modelJson)),
                  }),
                ),
              )
            }
          >
            Выполнить расчёт <ArrowRight size={17} />
          </button>
          {modelResult !== null && (
            <div className="wb-preview">
              <strong>Результат модели</strong>
              <pre>{pretty(modelResult)}</pre>
            </div>
          )}
        </div>
      )}
    </>
  );
}
