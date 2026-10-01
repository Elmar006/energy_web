"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight, Info } from "lucide-react";
import Link from "next/link";
import { api, DatasetList } from "./workbench-shared";

export default function CsvSection() {
  const {
    section,
    spec,
    scenario,
    onSaved,
    name,
    source,
    datasetName,
    kind,
    license,
    timeZone,
    dateFrom,
    dateTo,
    coverage,
    csvType,
    csvFile,
    datasets,
    busy,
    reloadDatasets,
    perform,
    metadata,
    setTimeZone,
    setDateFrom,
    setDateTo,
    setCoverage,
    setCsvFile,
    setMessage,
  } = useWorkbench();
  return (
    <>
      {section === "csv" && (
        <div className="wb-body">
          {!scenario && <div className="prerequisite" role="note"><strong>Сначала выберите сохранённый сценарий</strong><p>Выберите его вверху страницы или создайте новый.</p><Link className="secondary-button" href="/data/scenario">Создать сценарий</Link></div>}
          {scenario && <p className="wb-note"><Info size={17} aria-hidden="true" /> Импорт создаст новую версию сценария. Происхождение данных указывает поставщик.</p>}
          <div className="wb-segment">
            <Link
              href={`/data/csv/sessions${scenario ? `?scenario=${scenario.id}` : ""}`}
              className={csvType === "sessions" ? "active" : ""}
            >
              Выполненные зарядки
            </Link>
            <Link
              href={`/data/csv/grid${scenario ? `?scenario=${scenario.id}` : ""}`}
              className={csvType === "grid-headroom" ? "active" : ""}
            >
              Резерв сети
            </Link>
          </div>
          <p className="wb-help">
            Сценарий:{" "}
            <strong>{scenario?.name || "сначала сохраните сценарий"}</strong>.{" "}
            {csvType === "sessions"
              ? "Зоны: " +
                (spec?.zones ?? []).map((item) => item.id).join(", ") +
                ". CSV: session_id,zone_id,started_at,ended_at,energy_kwh. История сессий не учитывает неудовлетворённый спрос."
              : "Узлы: " +
                (spec?.grid_nodes ?? []).map((item) => item.id).join(", ") +
                ". CSV: grid_node_id,hour,headroom_kw; все часы 0–23."}
          </p>
          {metadata}
          <div className="wb-fields">
            <label className="wb-field">
              <span>Часовой пояс IANA</span>
              <input
                value={timeZone}
                onChange={(event) => setTimeZone(event.target.value)}
              />
            </label>
            <label className="wb-field">
              <span>
                {csvType === "sessions" ? "Начало периода" : "Дата профиля"}
              </span>
              <input
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </label>
            {csvType === "sessions" && (
              <label className="wb-field">
                <span>Конец периода</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(event) => setDateTo(event.target.value)}
                />
              </label>
            )}
          </div>
          {csvType === "sessions" && (
            <label className="wb-check">
              <input
                type="checkbox"
                checked={coverage}
                onChange={(event) => setCoverage(event.target.checked)}
              />{" "}
              Подтверждаю полноту выгрузки по всем зонам и дням; пустые дни
              означают ноль сессий
            </label>
          )}
          <label className="wb-field">
            <span>
              Исходный CSV · до {csvType === "sessions" ? 50 : 10} МиБ
            </span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setCsvFile(event.target.files?.[0] || null)}
            />
          </label>
          <button
            className="primary-button"
            disabled={
              busy ||
              !scenario ||
              !csvFile ||
              !name.trim() ||
              !source.trim() ||
              !datasetName.trim() ||
              !dateFrom ||
              (csvType === "sessions" && !dateTo)
            }
            onClick={() =>
              void perform(async () => {
                if (!scenario || !csvFile) return;
                const form = new FormData();
                Object.entries({
                  scenario_name: name,
                  dataset_name: datasetName,
                  source,
                  kind,
                  time_zone: timeZone,
                  license,
                  ...(csvType === "sessions"
                    ? {
                        start_date: dateFrom,
                        end_date: dateTo,
                        coverage_complete: String(coverage),
                      }
                    : { profile_date: dateFrom }),
                }).forEach(([key, value]) => {
                  if (value) form.set(key, value);
                });
                form.set("file", csvFile);
                const body = await api(
                  "scenarios/" + scenario.id + "/imports/" + csvType,
                  { method: "POST", body: form },
                );
                onSaved(body.scenario);
                setMessage(
                  "Новый снимок: " +
                    body.scenario.name +
                    " · SHA-256 " +
                    body.sha256,
                );
                await reloadDatasets();
              })
            }
          >
            Импортировать и создать снимок <ArrowRight size={17} />
          </button>
          <DatasetList
            datasets={datasets.filter((item) => item.format === "csv")}
          />
        </div>
      )}
    </>
  );
}
