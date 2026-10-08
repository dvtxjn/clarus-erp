import { useEffect, useMemo, useRef, useState } from "react";
import type { CustomCellEditorProps } from "ag-grid-react";

/**
 * Date cells, Google-Sheets style (client, 2026-09-29): double-click (or start typing) and a
 * small calendar opens under the cell. Type a date ("8/10", "8 oct", "08-10-2026",
 * "2026-10-08") and press Enter, or click a day. Clear empties the cell.
 *
 * format "iso": the value is "2026-10-08" (real date columns).
 * format "sheet": the value is text "08-Oct-2026" (INW, typed like the sheet).
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DOW = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
export type Format = "iso" | "sheet";

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const formatTypedDate = (d: Date, f: Format) => (f === "iso" ? iso(d) : `${pad(d.getDate())}-${MONTHS[d.getMonth()]}-${d.getFullYear()}`);

function valid(y: number, m: number, d: number): Date | null {
  const dt = new Date(y, m, d);
  return dt.getFullYear() === y && dt.getMonth() === m && dt.getDate() === d ? dt : null;
}

/** Day first, like the sheet: "8/10" = 8 October. Missing year = nearest to today. */
export function parseTypedDate(text: string, now = new Date()): Date | null {
  const t = text.trim().toLowerCase();
  if (!t) return null;
  const year = (y?: string) => (!y ? now.getFullYear() : y.length === 2 ? 2000 + Number(y) : Number(y));
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return valid(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  // no year typed: the year that puts the date nearest today (±6 months)
  const near = (mon: number, day: number) =>
    [now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].reduce((b, c) =>
      Math.abs(new Date(c, mon, day).getTime() - now.getTime()) < Math.abs(new Date(b, mon, day).getTime() - now.getTime()) ? c : b,
    );
  m = t.match(/^(\d{1,2})[-/. ](\d{1,2})(?:[-/. ](\d{2}|\d{4}))?$/);
  if (m) return valid(m[3] ? year(m[3]) : near(Number(m[2]) - 1, Number(m[1])), Number(m[2]) - 1, Number(m[1]));
  m = t.match(/^(\d{1,2})[-/. ]?([a-z]{3})[a-z]*(?:[-/. ,]+(\d{2}|\d{4}))?$/);
  if (m) {
    const mon = MONTHS.findIndex((x) => x.toLowerCase() === m![2]);
    return mon < 0 ? null : valid(m[3] ? year(m[3]) : near(mon, Number(m[1])), mon, Number(m[1]));
  }
  return null;
}

function fromValue(v: unknown): Date | null {
  if (typeof v !== "string" || !v) return null;
  return parseTypedDate(v);
}

export default function DateCellEditor(props: CustomCellEditorProps<unknown, string | null> & { format?: Format }) {
  const format: Format = props.format ?? "iso";
  const start = fromValue(props.initialValue);
  // typing a character starts the edit with that character, like any cell
  const [text, setText] = useState(() => (props.eventKey && props.eventKey.length === 1 ? props.eventKey : ""));
  const typed = useMemo(() => parseTypedDate(text), [text]);
  const [view, setView] = useState(() => {
    const d = start ?? new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    if (typed) setView(new Date(typed.getFullYear(), typed.getMonth(), 1));
  }, [typed]);

  const pick = (d: Date | null) => {
    props.onValueChange(d ? formatTypedDate(d, format) : null);
    // let the grid read the new value before it closes the editor
    setTimeout(() => props.stopEditing(), 0);
  };

  const first = (view.getDay() + 6) % 7; // Monday first
  const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
  const cells: (Date | null)[] = [...Array(first).fill(null), ...Array.from({ length: days }, (_, i) => new Date(view.getFullYear(), view.getMonth(), i + 1))];
  const today = iso(new Date());
  const chosen = typed ?? start;

  return (
    <div className="date-editor" onMouseDown={(e) => e.stopPropagation()}>
      <input
        ref={input}
        className="date-editor-input"
        value={text}
        placeholder={start ? formatTypedDate(start, "sheet") : "Type e.g. 8/10 or 8 Oct"}
        onChange={(e) => {
          setText(e.target.value);
          // keep the grid's value in step with the typing: the grid can take Enter before this input
          // sees it, and then it saves whatever was last handed over (findings 2026-10-07, item 5)
          const d = parseTypedDate(e.target.value);
          props.onValueChange(d ? formatTypedDate(d, format) : ((props.initialValue as string | null) ?? null));
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            e.stopPropagation();
            if (!text.trim()) return props.stopEditing(); // nothing typed: keep the value
            if (typed) pick(typed);
          }
        }}
      />
      {text.trim() && !typed && <div className="date-editor-hint">Not a date yet — day first: 8/10, 8 Oct, 08-10-2026</div>}
      <div className="date-editor-head">
        <button type="button" onClick={() => setView(new Date(view.getFullYear(), view.getMonth() - 1, 1))} aria-label="Previous month">
          ‹
        </button>
        <span>
          {MONTHS[view.getMonth()]} {view.getFullYear()}
        </span>
        <button type="button" onClick={() => setView(new Date(view.getFullYear(), view.getMonth() + 1, 1))} aria-label="Next month">
          ›
        </button>
      </div>
      <div className="date-editor-grid">
        {DOW.map((d) => (
          <span key={d} className="date-editor-dow">
            {d}
          </span>
        ))}
        {cells.map((d, i) =>
          d ? (
            <button
              type="button"
              key={i}
              className={[
                "date-editor-day",
                iso(d) === today ? "is-today" : "",
                chosen && iso(d) === iso(chosen) ? "is-chosen" : "",
              ].join(" ")}
              onClick={() => pick(d)}
            >
              {d.getDate()}
            </button>
          ) : (
            <span key={i} />
          ),
        )}
      </div>
      <div className="date-editor-foot">
        <button type="button" className="btn-secondary" onClick={() => pick(new Date())}>
          Today
        </button>
        <button type="button" className="btn-secondary" onClick={() => pick(null)}>
          Clear
        </button>
      </div>
    </div>
  );
}
