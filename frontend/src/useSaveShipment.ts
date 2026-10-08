import { useCallback } from "react";
import { ShipmentConflictError, updateShipment, type ShipmentConflict } from "./api";
import { useConfirm } from "./ConfirmDialog";
import { rememberShipment } from "./detailCache";
import type { Shipment } from "./types";

/** The values `seen` had for the fields `changes` touches (sent as `base`). */
export function baseFor(seen: Shipment, changes: Partial<Shipment>): Record<string, unknown> {
  const base: Record<string, unknown> = {};
  for (const key of Object.keys(changes) as (keyof Shipment)[]) {
    if (key === "custom_fields") {
      const custom: Record<string, unknown> = {};
      for (const k of Object.keys(changes.custom_fields ?? {})) custom[k] = seen.custom_fields?.[k] ?? null;
      base.custom_fields = custom;
    } else {
      base[key] = seen[key] ?? null;
    }
  }
  return base;
}

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "(blank)" : v === true ? "Yes" : v === false ? "No" : String(v));

export function conflictText(c: ShipmentConflict, label?: string): string {
  const who = c.changed_by ?? "Someone";
  const when = c.changed_at
    ? ` at ${new Date(c.changed_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}`
    : "";
  return `${who} changed ${label ?? c.field.replace(/_/g, " ")} to “${show(c.current)}”${when}, after you opened it. You entered “${show(c.yours)}”.`;
}

export type SaveOutcome = { shipment: Shipment; kept: "saved" | "mine" | "theirs" };

/**
 * Save shipment fields without overwriting a colleague: sends what the user saw as
 * `base`; if someone changed the same field meanwhile, asks "Keep mine / Use theirs".
 * `seen` = the shipment as the user saw it before this edit.
 */
export function useSaveShipment() {
  const confirm = useConfirm();
  return useCallback(
    async (seen: Shipment, changes: Partial<Shipment>, label?: string): Promise<SaveOutcome> => {
      const out = await save(seen, changes, label);
      rememberShipment(out.shipment); // a reopened peek shows this save at once
      return out;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- save is defined below and only reads confirm
    [confirm],
  );
  async function save(seen: Shipment, changes: Partial<Shipment>, label?: string): Promise<SaveOutcome> {
      try {
        return { shipment: await updateShipment(seen.id, changes, baseFor(seen, changes)), kept: "saved" };
      } catch (e) {
        if (!(e instanceof ShipmentConflictError)) throw e;
        const keep = await confirm({
          title: "Someone else changed this",
          message: e.conflicts.map((c) => conflictText(c, e.conflicts.length === 1 ? label : undefined)).join(" "),
          confirmLabel: "Keep mine",
          cancelLabel: "Use theirs",
        });
        if (!keep) return { shipment: e.shipment, kept: "theirs" };
        // Keep mine: save again against the values that are there now
        return { shipment: await updateShipment(seen.id, changes, baseFor(e.shipment, changes)), kept: "mine" };
      }
  }
}
