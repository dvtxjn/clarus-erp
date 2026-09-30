/** Shared bits for ICEGATE mail screens. Times are shown in India time (client: GMT+5:30). */
export const istTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
