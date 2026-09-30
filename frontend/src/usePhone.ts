import { useEffect, useState } from "react";

/** Phone-width screens get the mobile layouts (bottom tabs, shipment cards, proforma line list). */
export const PHONE_QUERY = "(max-width: 767px)";

export function usePhone(): boolean {
  const [phone, setPhone] = useState(() => typeof window !== "undefined" && window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const on = () => setPhone(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return phone;
}
