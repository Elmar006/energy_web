"use client";

import { useWorkbench } from "./workbench-state";
import { ArrowRight, Info } from "lucide-react";
import { MobilityFields } from "@/components/demand-fields";
import { api, pretty, JsonEditor } from "./workbench-shared";

export default function MobilitySection() {
  const {
    view,
    spec,
    onSaved,
    name,
    mobilityJson,
    preview,
    previewPayload,
    accessToken,
    busy,
    perform,
    jsonHeaders,
    setName,
    setMobilityJson,
    setPreview,
    setPreviewPayload,
    setAccessToken,
    setMessage,
  } = useWorkbench();
  return (
    <>
      {view === "mobility" && (
        <div className="wb-body">
          <p className="wb-note">
            <Info size={17} /> Потенциальные заявки из переданных маршрутов.
            Публичная зарядка условно учтена при проверке возможности
            последующих поездок; репрезентативность маршрутов подтверждает
            поставщик.
          </p>
          <p className="wb-help">
            Зоны: {(spec?.zones ?? []).map((item) => item.id).join(", ")}. Время с
            UTC-смещением, расстояние в км, энергия в кВт·ч. Укажите
            covered_dates, replace_zone_ids, источник, машины и активности.
          </p>
          <MobilityFields
            value={mobilityJson}
            onChange={setMobilityJson}
            zones={(spec?.zones ?? []).map((item) => item.id)}
          />
          <details className="wb-advanced">
            <summary>Машины, поездки и стоянки · полный JSON</summary>
            <JsonEditor
              label="MobilityInput JSON"
              value={mobilityJson}
              setValue={setMobilityJson}
              rows={24}
            />
          </details>
          <label className="wb-field">
            <span>Имя сохраняемого сценария</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <div className="wb-actions">
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  const payload = {
                    input: spec,
                    mobility: JSON.parse(mobilityJson),
                  };
                  setPreviewPayload(payload);
                  setPreview(
                    await api("scenarios/from-mobility/preview", {
                      method: "POST",
                      headers: jsonHeaders,
                      body: pretty(payload),
                    }),
                  );
                })
              }
            >
              Рассчитать предварительный спрос
            </button>
            <button
              className="primary-button"
              disabled={busy || !preview || !previewPayload || !name.trim()}
              onClick={() =>
                void perform(async () => {
                  const body = await api("scenarios/from-mobility", {
                    method: "POST",
                    headers: jsonHeaders,
                    body: pretty({ name, ...previewPayload }),
                  });
                  onSaved(body.scenario);
                  setAccessToken(body.source_access_token);
                  setMessage(
                    "Сохранён источник маршрутов: SHA-256 " +
                      body.source_sha256,
                  );
                })
              }
            >
              Сохранить источник и сценарий <ArrowRight size={17} />
            </button>
          </div>
          {preview && (
            <div className="wb-preview">
              <strong>
                Предпросмотр ·{" "}
                {Array.isArray(preview.requests) ? preview.requests.length : 0}{" "}
                заявок
              </strong>
              <p>
                Планировщик использует датированные окна; почасовой ряд служит
                контрольной сводкой.
              </p>
              <pre>
                {pretty({
                  audit: preview.audit,
                  requests: preview.requests,
                  source_sha256: preview.source_sha256,
                })}
              </pre>
            </div>
          )}
          {accessToken && (
            <div className="wb-secret">
              <strong>Одноразовый ключ к исходным маршрутам</strong>
              <p>
                Сохраните его сейчас. Повторно получить ключ нельзя; не
                вставляйте его в URL.
              </p>
              <code>{accessToken}</code>
              <button
                className="secondary-button"
                onClick={() => void navigator.clipboard.writeText(accessToken)}
              >
                Скопировать
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
