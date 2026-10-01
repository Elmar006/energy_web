"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight, Info, RefreshCw } from "lucide-react";
import Select from "@/components/ui/select";
import {
  api,
  pretty,
  roles,
  JsonEditor,
  DatasetList,
} from "./workbench-shared";

export default function GeoSection() {
  const {
    section,
    onSaved,
    source,
    datasetName,
    kind,
    license,
    timeZone,
    dateFrom,
    geoFile,
    datasets,
    versions,
    optionsJson,
    parametersJson,
    scenariosJson,
    preview,
    previewPayload,
    busy,
    reloadDatasets,
    perform,
    jsonHeaders,
    builder,
    metadata,
    setTimeZone,
    setDateFrom,
    setGeoFile,
    setVersions,
    setOptionsJson,
    setParametersJson,
    setScenariosJson,
    setPreview,
    setPreviewPayload,
    setMessage,
  } = useWorkbench();
  return (
    <>
      {section === "geo" && (
        <div className="wb-body">
          <p className="wb-note">
            <Info size={17} /> Четыре GeoJSON FeatureCollection: demand_zone,
            candidate_site, grid_node и travel_edge. Расчётные параметры — в свойствах объектов.
          </p>
          {metadata}
          <div className="wb-fields">
            <label className="wb-field">
              <span>Дата наблюдения · обязательна для observed</span>
              <input
                type="datetime-local"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </label>
            <label className="wb-field">
              <span>GeoJSON · до 50 МиБ</span>
              <input
                type="file"
                accept=".json,.geojson,application/geo+json"
                onChange={(event) =>
                  setGeoFile(event.target.files?.[0] || null)
                }
              />
            </label>
            <label className="wb-field">
              <span>Часовой пояс IANA</span>
              <input
                value={timeZone}
                onChange={(event) => setTimeZone(event.target.value)}
              />
            </label>
          </div>
          <div className="wb-actions">
            <button
              className="secondary-button"
              disabled={
                busy ||
                !geoFile ||
                !source.trim() ||
                !datasetName.trim() ||
                (kind === "observed" && !dateFrom)
              }
              onClick={() =>
                void perform(async () => {
                  if (!geoFile) return;
                  const form = new FormData();
                  form.set("file", geoFile);
                  form.set("name", datasetName);
                  form.set("source", source);
                  form.set("kind", kind);
                  if (license) form.set("license", license);
                  if (dateFrom)
                    form.set("captured_at", new Date(dateFrom).toISOString());
                  const body = await api("datasets/import", {
                    method: "POST",
                    body: form,
                  });
                  setMessage(
                    "Слой " +
                      body.dataset_id +
                      " · " +
                      body.features +
                      " объектов · SHA-256 " +
                      body.sha256,
                  );
                  await reloadDatasets();
                })
              }
            >
              Загрузить слой
            </button>
            <button
              className="text-button"
              onClick={() => void reloadDatasets()}
            >
              <RefreshCw size={15} /> Обновить версии
            </button>
          </div>
          <div className="wb-roles">
            {roles.map(([role, label]) => (
              <div className="wb-field" key={role}>
                <span>{label}</span>
                <Select
                  label={label}
                  value={versions[role] || ""}
                  onValueChange={(value) =>
                    setVersions((current) => ({
                      ...current,
                      [role]: value,
                    }))
                  }
                  options={[
                    { value: "", label: "Выберите версию набора" },
                    ...datasets
                      .filter((item) => item.format === "geojson")
                      .map((item) => ({
                        value: item.id,
                        label:
                          item.name +
                          " · " +
                          item.id.slice(0, 8) +
                          " · " +
                          item.kind,
                      })),
                  ]}
                />
              </div>
            ))}
          </div>
          <JsonEditor
            label="Варианты оборудования · JSON"
            value={optionsJson}
            setValue={setOptionsJson}
            rows={7}
          />
          <JsonEditor
            label="Параметры · JSON"
            value={parametersJson}
            setValue={setParametersJson}
            rows={10}
          />
          <JsonEditor
            label="Сценарии неопределённости · JSON"
            value={scenariosJson}
            setValue={setScenariosJson}
            rows={6}
          />
          <div className="wb-actions">
            <button
              className="secondary-button"
              disabled={busy || roles.some(([role]) => !versions[role])}
              onClick={() =>
                void perform(async () => {
                  const payload = builder();
                  setPreviewPayload(payload);
                  setPreview(
                    await api("scenarios/from-datasets/preview", {
                      method: "POST",
                      headers: jsonHeaders,
                      body: pretty(payload),
                    }),
                  );
                })
              }
            >
              Проверить сборку
            </button>
            <button
              className="primary-button"
              disabled={busy || !preview || !previewPayload}
              onClick={() =>
                void perform(async () => {
                  const body = await api("scenarios/from-datasets", {
                    method: "POST",
                    headers: jsonHeaders,
                    body: pretty(previewPayload),
                  });
                  onSaved(body.scenario);
                  setPreview(null);
                  setMessage("Сохранён сценарий: " + body.scenario.name);
                })
              }
            >
              Сохранить сценарий <ArrowRight size={17} />
            </button>
          </div>
          {preview && (
            <div className="wb-preview">
              <strong>Качество исходных данных</strong>
              <pre>{pretty(preview.data_quality)}</pre>
            </div>
          )}
          <DatasetList
            datasets={datasets.filter((item) => item.format === "geojson")}
          />
        </div>
      )}
    </>
  );
}
