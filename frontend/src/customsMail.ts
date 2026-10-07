import { fmtWhen } from "./dates";
/** Shared bits for ICEGATE mail screens. Times are shown in India time (client: GMT+5:30). */
export const istTime = (iso: string | null) => fmtWhen(iso);
