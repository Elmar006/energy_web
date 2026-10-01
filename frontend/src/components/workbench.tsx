"use client";

import Link from "next/link";
import type { Props } from "./workbench-shared";
import { useWorkbenchController, WorkbenchProvider } from "./workbench-state";
import ScenarioSection from "./workbench-scenario";
import CsvSection from "./workbench-csv";
import GeoSection from "./workbench-geo";
import DatedSection from "./workbench-dated";
import MobilitySection from "./workbench-mobility";
import ModelsSection from "./workbench-models";

export default function Workbench(props: Props) {
  const state = useWorkbenchController(props);
  const { view, section, scenario, error, message } = state;
  return (
    <WorkbenchProvider value={state}>
      <section className="workbench">
        <div className="wb-heading">
          <div>
            <h2>
              {view === "data"
                ? section === "editor" ? "Редактор сценария" : section === "csv" ? "Табличные источники" : section === "geo" ? "Территория и геоданные" : "Заявки и календарь"
                : view === "mobility"
                  ? "Поездки и стоянки"
                  : "Параметры"}
            </h2>
          </div>
          <span className="wb-context-label">{scenario ? scenario.name : "Черновик"}</span>
        </div>
        {view === "data" && (
          <>
            <nav className="wb-tabs" aria-label="Способ подготовки данных">
              {(
                [
                  ["editor", "scenario", "Сценарий"],
                  ["csv", "csv/sessions", "CSV сессий и сети"],
                  ["geo", "geo", "Геоданные"],
                  ["dated", "dated", "Датированный спрос"],
                ] as const
              ).map(([id, path, label]) => (
                <Link
                  key={id}
                  href={`/data/${path}${scenario ? `?scenario=${scenario.id}` : ""}`}
                  aria-current={section === id ? "page" : undefined}
                  className={section === id ? "active" : ""}
                >
                  {label}
                </Link>
              ))}
            </nav>
            <ScenarioSection />
            <CsvSection />
            <GeoSection />
            <DatedSection />
          </>
        )}
        <MobilitySection />
        <ModelsSection />
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="wb-success" role="status">
            {message}
          </p>
        )}
      </section>
    </WorkbenchProvider>
  );
}
