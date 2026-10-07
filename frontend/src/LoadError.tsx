/** A failed load, said plainly with a way out — never the "nothing here" empty text. */
export default function LoadError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="tracker-empty" role="alert">
      Couldn't load {what}.{" "}
      <button type="button" className="link-btn" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
