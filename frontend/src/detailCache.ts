import type { Shipment, ShipmentDocument } from "./types";

/** Jobs already opened this session: reopening draws at once from here while a fresh copy loads behind it. */
export const shipmentCache = new Map<number, Shipment>();
/** Documents per shipment, last loaded — shared by the Overview's CFS / shipping line blocks. */
export const docsCache = new Map<number, ShipmentDocument[]>();

/** A save anywhere (tracker cell, chip, peek) keeps the cached copy current. */
export function rememberShipment(s: Shipment): void {
  if (shipmentCache.has(s.id)) shipmentCache.set(s.id, s);
}

/** Changed elsewhere (another person, live update): drop the copy so the next open loads fresh. */
export function forgetShipment(id: number): void {
  shipmentCache.delete(id);
}
