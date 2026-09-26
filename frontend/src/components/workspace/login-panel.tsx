"use client";

import Image from "next/image";
import { ArrowRight } from "lucide-react";

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
    <main className="screen-centered">
      <div className="login-panel">
        <div className="brand-mark">
          <Image src="/icon.svg" width={48} height={48} alt="" />
        </div>
        <p className="eyebrow">Платформа планирования</p>
        <h1>EV Infrastructure</h1>
        <p>Инженерные решения для зарядной сети, проверенные моделированием.</p>
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
      </div>
    </main>
  );
}
