import { t } from "@/lib/text";

export default function NotFound() {
  return (
    <main className="shell">
      <section className="panel">
        <h1>404</h1>
        <p className="muted">{t("en", "notFoundMessage")}</p>
      </section>
    </main>
  );
}
