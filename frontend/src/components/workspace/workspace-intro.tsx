import { MapPinned, ShieldCheck } from "lucide-react";

export default function WorkspaceIntro({
  scenarioName,
}: {
  scenarioName?: string;
}) {
  return (
    <section className="page-intro" aria-labelledby="page-title">
      <div>
        <p className="eyebrow">
          <MapPinned size={14} /> ПРОЕКТ / СЦЕНАРНОЕ ПЛАНИРОВАНИЕ
        </p>
        <h1 id="page-title">Развитие зарядной сети</h1>
        <p>
          Выберите условия и получите план размещения с проверкой энергосети и
          спроса.
        </p>
      </div>
      <div className="intro-note">
        <ShieldCheck size={19} />
        <span>
          {scenarioName ? "Загруженный сценарий" : "Пилотный сценарий"}
          <br />
          <strong>
            {scenarioName ?? "Екатеринбург · синтетические данные"}
          </strong>
        </span>
      </div>
    </section>
  );
}
