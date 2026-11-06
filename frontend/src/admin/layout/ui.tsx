// Small layout pieces every staff screen uses. The classes are in
// ui.module.css, imported as `ui` by screens that need one directly.
import type { ReactNode } from "react";
import { Link } from "react-router";
import ui from "./ui.module.css";

/** The screen's title, an optional "back" link above it and its main
 * actions at the row's end. */
export function PageHead({
  title,
  back,
  actions,
}: {
  title: ReactNode;
  back?: { to: string; label: string };
  actions?: ReactNode;
}) {
  return (
    <>
      {back && (
        <Link className={ui.back} to={back.to}>
          {back.label}
        </Link>
      )}
      <div className={ui.head}>
        <h1>{title}</h1>
        {actions && <div className={ui.actions}>{actions}</div>}
      </div>
    </>
  );
}

/** A section of the screen, with its title. */
export function Panel({
  title,
  children,
}: {
  title?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={ui.panel}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

/** One form field: its label, the field itself and its error. */
export function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: ReactNode;
  error?: string | null | false;
  children: ReactNode;
}) {
  return (
    <div className={ui.field}>
      <label htmlFor={id}>{label}</label>
      {children}
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
