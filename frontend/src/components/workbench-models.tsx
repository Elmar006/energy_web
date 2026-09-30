"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight, Info } from "lucide-react";
import ModelFields from "@/components/model-fields";
import ModelResultView from "@/components/model-result";
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
              ? "Задайте длину маршрута, характеристики автомобиля и станции по пути."
              : "Добавьте машины, назначенные рейсы и доступные окна зарядки. Время задаётся номерами интервалов от начала горизонта."}
          </p>
          <fieldset className="model-inputs" disabled={busy}>
          <legend className="sr-only">Параметры отдельной модели</legend>
          <ModelFields
            model={model}
            value={modelJson}
            onChange={value => { setModelJson(value); setModelResult(null); }}
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
              setValue={value => { setModelJson(value); setModelResult(null); }}
              rows={22}
            />
          </details>
          </fieldset>
          <button
            className="primary-button"
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                setModelResult(null);
                setModelResult(
                  await api(model, {
                    method: "POST",
                    headers: jsonHeaders,
                    body: pretty(JSON.parse(modelJson)),
                  }),
                ); },
              )
            }
          >
            Выполнить расчёт <ArrowRight size={17} />
          </button>
          {modelResult !== null && <ModelResultView value={modelResult} />}
        </div>
      )}
    </>
  );
}
