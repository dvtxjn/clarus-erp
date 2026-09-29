/**
 * Clarus wordmark: "clarus" + ↗ arrow in brand orange.
 * Recreated as vector from the client's logo image — swap in the original
 * SVG/PNG export when available.
 */
export const BRAND_ORANGE = "#D26B21";

export default function ClarusLogo({ height = 22, title = "Clarus" }: { height?: number; title?: string }) {
  return (
    <svg
      viewBox="0 0 400 96"
      height={height}
      role="img"
      aria-label={title}
      className="clarus-logo"
      xmlns="http://www.w3.org/2000/svg"
    >
      <text
        x="0"
        y="84"
        fill={BRAND_ORANGE}
        fontFamily="Inter, 'Helvetica Neue', Arial, sans-serif"
        fontWeight={800}
        fontSize="104"
        letterSpacing="-3"
      >
        clarus
      </text>
      {/* ↗ arrow: top bar, right bar, diagonal */}
      <path
        fill={BRAND_ORANGE}
        d="M334 4 H388 V58 H377 V22.8 L339.6 60.2 L331.8 52.4 L369.2 15 H334 Z"
      />
    </svg>
  );
}
