"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Select from "@/components/ui/select";
import {
  api,
  pretty,
  type Dataset,
  type Obj,
  type Props,
} from "./workbench-shared";

export function useWorkbenchController({
  view,
  section,
  model,
  csvType,
  spec,
  scenario,
  onSaved,
}: Props) {
  const router = useRouter();
  const [name, setName] = useState("Новый сценарий");
  const [source, setSource] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [kind, setKind] = useState("assumed");
  const [license, setLicense] = useState("");
  const [timeZone, setTimeZone] = useState("Europe/Moscow");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [coverage, setCoverage] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [geoFile, setGeoFile] = useState<File | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [specJson, setSpecJson] = useState(pretty(spec));
  const [optionsJson, setOptionsJson] = useState(
    pretty((spec as unknown as Obj).options || []),
  );
  const [parametersJson, setParametersJson] = useState(pretty(spec.parameters));
  const [scenariosJson, setScenariosJson] = useState(pretty(spec.scenarios));
  const [mobilityJson, setMobilityJson] = useState(
    pretty({
      schema_version: "mobility-v1",
      time_zone: "Europe/Moscow",
      covered_dates: [],
      replace_zone_ids: [],
      source: "",
      source_kind: "assumed",
      vehicles: [],
    }),
  );
  const [datedJson, setDatedJson] = useState(
    pretty({
      schema_version: "demand-dataset-v1",
      service_calendar: {},
      charging_requests: [],
    }),
  );
  const [modelJson, setModelJson] = useState("{}");
  const [preview, setPreview] = useState<Obj | null>(null);
  const [previewPayload, setPreviewPayload] = useState<Obj | null>(null);
  const [modelResult, setModelResult] = useState<unknown>(null);
  const [accessToken, setAccessToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (view === "data" && section === "geo") void reloadDatasets();
  }, [view, section]);

  useEffect(() => {
    if (section !== "editor") return;
    const draft = sessionStorage.getItem("energy-planner:scenario-draft");
    if (!draft) return;
    sessionStorage.removeItem("energy-planner:scenario-draft");
    const timer = window.setTimeout(() => setSpecJson(draft), 0);
    return () => window.clearTimeout(timer);
  }, [section]);

  async function reloadDatasets() {
    try {
      setDatasets(await api("datasets"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Список недоступен");
    }
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (caught) {
      setPreview(null);
      setPreviewPayload(null);
      setError(
        caught instanceof Error ? caught.message : "Операция не выполнена",
      );
    } finally {
      setBusy(false);
    }
  }
  async function saveScenario(input: unknown) {
    const response = await fetch("/api/scenarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, spec: input }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Сценарий не сохранён");
    onSaved(body);
    setMessage("Сохранён новый неизменяемый сценарий: " + body.name);
  }
  const jsonHeaders = { "Content-Type": "application/json" };
  const builder = () => ({
    name,
    input_id: "input-" + Date.now(),
    time_zone: timeZone,
    dataset_versions: versions,
    options: JSON.parse(optionsJson),
    parameters: JSON.parse(parametersJson),
    scenarios: JSON.parse(scenariosJson),
  });
  const metadata = (
    <div className="wb-fields">
      <label className="wb-field">
        <span>Имя нового сценария</span>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={120}
        />
      </label>
      <label className="wb-field">
        <span>Название набора</span>
        <input
          value={datasetName}
          onChange={(event) => setDatasetName(event.target.value)}
        />
      </label>
      <label className="wb-field">
        <span>Источник и основание</span>
        <input
          value={source}
          onChange={(event) => setSource(event.target.value)}
        />
      </label>
      <div className="wb-field">
        <span>Происхождение</span>
        <Select
          label="Происхождение"
          value={kind}
          onValueChange={setKind}
          options={[
            { value: "assumed", label: "Сценарное допущение" },
            { value: "derived", label: "Вычислено" },
            { value: "observed", label: "Заявлено как наблюдение" },
          ]}
        />
      </div>
      <label className="wb-field">
        <span>Условия использования</span>
        <input
          value={license}
          onChange={(event) => setLicense(event.target.value)}
        />
      </label>
    </div>
  );

  return {
    view,
    section,
    model,
    spec,
    scenario,
    onSaved,
    router,
    name,
    setName,
    source,
    setSource,
    datasetName,
    setDatasetName,
    kind,
    setKind,
    license,
    setLicense,
    timeZone,
    setTimeZone,
    dateFrom,
    setDateFrom,
    dateTo,
    setDateTo,
    coverage,
    setCoverage,
    csvType,
    csvFile,
    setCsvFile,
    geoFile,
    setGeoFile,
    datasets,
    setDatasets,
    versions,
    setVersions,
    specJson,
    setSpecJson,
    optionsJson,
    setOptionsJson,
    parametersJson,
    setParametersJson,
    scenariosJson,
    setScenariosJson,
    mobilityJson,
    setMobilityJson,
    datedJson,
    setDatedJson,
    modelJson,
    setModelJson,
    preview,
    setPreview,
    previewPayload,
    setPreviewPayload,
    modelResult,
    setModelResult,
    accessToken,
    setAccessToken,
    busy,
    setBusy,
    error,
    setError,
    message,
    setMessage,
    reloadDatasets,
    perform,
    saveScenario,
    jsonHeaders,
    builder,
    metadata,
  };
}

const Context = createContext<ReturnType<typeof useWorkbenchController> | null>(
  null,
);

export const WorkbenchProvider = Context.Provider;

export function useWorkbench() {
  const value = useContext(Context);
  if (!value) throw new Error("WorkbenchProvider отсутствует");
  return value;
}
