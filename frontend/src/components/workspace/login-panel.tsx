"use client";

import Image from "next/image";
import { ArrowRight } from "lucide-react";
import NetworkFigure from "./network-figure";

export default function LoginPanel({
  password,
  onPasswordChange,
  onSubmit,
  error,
}: {
  password: string;
  onPasswordChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => Promise<void>;
  error: string;
}) {
  return (
    <main className="login-screen">
      <section className="login-story" aria-label="О платформе">
        <div className="login-brand"><Image src="/icon.svg" width={40} height={40} alt="" /><span>EV Infrastructure</span></div>
        <div className="login-story-content"><span className="empty-label">Планирование зарядной сети</span><h2>Где строить.<br />Как развивать.</h2><p>От исходных данных — к размещению, энергоснабжению и инвестициям.</p><NetworkFigure /></div>
        <span className="login-story-foot">Данные. Модель. Проверяемое решение.</span>
      </section>
      <div className="login-form-area">
      <div className="login-panel">
        <p className="eyebrow">EV Infrastructure</p>
        <h1>Рабочее<br />пространство</h1>
        <p>Введите пароль для доступа к сценариям и расчётам.</p>
        <form onSubmit={(event) => void onSubmit(event)}>
          <label htmlFor="password">Пароль доступа</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "password-error" : undefined}
            required
          />
          <button className="primary-button" type="submit">
            Открыть рабочее пространство <ArrowRight size={17} />
          </button>
        </form>
        {error && (
          <p id="password-error" className="error-banner" role="alert">
            {error}
          </p>
        )}
        <p className="login-access-note">Доступ предоставляется вашей командой.</p>
      </div>
      </div>
    </main>
  );
}
