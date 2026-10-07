import { useRef, useState } from "react";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-03" -> "03 Sep 2026" */
export function fmtDayMonth(iso: string | null | undefined): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : iso ?? "";
}

/**
 * What staff type -> "YYYY-MM-DD", day first: "03 Sep 2026", "3 sep", "3-Sep-26", "3/9", "03/09/2026",
 * "2026-09-03". No year = this year. "" for empty; null when it can't be read.
 */
export function parseDayMonth(text: string): string | null {
  const t = text.trim();
  if (!t) return "";
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
  let d: number, mo: number, y: number | undefined;
  if (iso) {
    [y, mo, d] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
  } else {
    const m = /^(\d{1,2})[\s/.-]*([a-z]{3,9}|\d{1,2})(?:[\s/.,-]+(\d{2}|\d{4}))?$/i.exec(t);
    if (!m) return null;
    d = Number(m[1]);
    mo = /^\d+$/.test(m[2]) ? Number(m[2]) : MONTHS.findIndex((x) => x.toLowerCase() === m[2].slice(0, 3).toLowerCase()) + 1;
    y = m[3] ? (m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3])) : new Date().getFullYear();
  }
  const dt = new Date(Date.UTC(y!, mo - 1, d));
  if (!mo || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/**
 * A date you type the way it's said ("03 Sep 2026", "3/9"), with a calendar button for picking —
 * instead of the browser's mm/dd/yyyy box. Commits on Enter or leaving it; Esc cancels.
 */
export default function DateInput({
  value,
  onCommit,
  onCancel,
  disabled,
  autoFocus,
  ariaLabel,
}: {
  value: string;
  onCommit: (iso: string) => void;
  onCancel?: () => void;
  disabled?: boolean;
  autoFocus?: boolean;
  ariaLabel?: string;
}) {
  const [text, setText] = useState(fmtDayMonth(value));
  const [bad, setBad] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const commit = () => {
    const iso = parseDayMonth(text);
    if (iso == null) return setBad(true);
    setBad(false);
    setText(fmtDayMonth(iso));
    onCommit(iso);
  };
  return (
    <span
      className="date-input"
      onBlur={(e) => {
        // the calendar button is part of the box: moving to it isn't leaving
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) commit();
      }}
    >
      <input
        type="text"
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        aria-label={ariaLabel}
        aria-invalid={bad || undefined}
        placeholder="03 Sep 2026…"
        value={text}
        disabled={disabled}
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => {
          setText(e.target.value);
          setBad(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
          if (e.key === "Escape" && onCancel) {
            e.preventDefault(); // cancels this box only, not the panel around it
            onCancel();
          }
        }}
      />
      <button
        type="button"
        className="date-input-cal"
        aria-label="Pick from a calendar"
        title="Pick from a calendar"
        disabled={disabled}
        onClick={() => {
          const p = picker.current;
          if (!p) return;
          p.value = parseDayMonth(text) || "";
          try {
            p.showPicker();
          } catch {
            p.focus();
          }
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
          <rect x="2" y="3" width="12" height="11" rx="2" />
          <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
        </svg>
      </button>
      <input
        ref={picker}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        className="date-input-picker"
        onChange={(e) => {
          if (!e.target.value) return;
          setText(fmtDayMonth(e.target.value));
          setBad(false);
          onCommit(e.target.value);
        }}
      />
      {bad && (
        <span className="date-input-error" role="alert">
          Try “03 Sep 2026” or “3/9”
        </span>
      )}
    </span>
  );
}
