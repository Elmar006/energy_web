"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight } from "lucide-react";
import ScenarioFields from "@/components/scenario-fields";
import { pretty, JsonEditor } from "./workbench-shared";

export default function ScenarioSection() {
  const {
    section,
    spec,
    name,
    specJson,
    busy,
    perform,
    saveScenario,
    setName,
    setSpecJson,
  } = useWorkbench();
  return (
    <>
      {section === "editor" && (
        <div className="wb-body">
          <label className="wb-field">
            <span>Имя новой версии</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <ScenarioFields value={specJson} onChange={setSpecJson} />
          <details className="wb-advanced">
            <summary>
              Полный JSON · оборудование, цены и дополнительные ограничения
            </summary>
            <JsonEditor
              label="PlanningInput JSON · кВт, кВт·ч, минуты, ₽"
              value={specJson}
              setValue={setSpecJson}
              rows={22}
            />
          </details>
          <div className="wb-actions">
            <button
              className="primary-button"
              disabled={busy || !name.trim()}
              onClick={() =>
                void perform(() => saveScenario(JSON.parse(specJson)))
              }
            >
              Сохранить версию <ArrowRight size={17} />
            </button>
            <button
              className="secondary-button"
              onClick={() => setSpecJson(pretty(spec ?? { id: "", zones: [], sites: [], grid_nodes: [], options: [], travel_edges: [], scenarios: [], parameters: { years: [], annual_budgets_rub: [] } }))}
            >
              Вернуть выбранный вход
            </button>
          </div>
        </div>
      )}
    </>
  );
}
