export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total === 0) return null;
  const page = Math.floor(offset / limit) + 1;
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const from = offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <p className="text-sm text-ink-500">
        Showing <span className="font-semibold text-ink-700">{from.toLocaleString()}</span>–
        <span className="font-semibold text-ink-700">{to.toLocaleString()}</span> of{" "}
        <span className="font-semibold text-ink-700">{total.toLocaleString()}</span>
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="rounded-lg px-3 py-1.5 text-sm font-medium text-ink-600 ring-1 ring-inset ring-ink-100 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-sm tabular-nums text-ink-400">
          {page} / {pageCount}
        </span>
        <button
          onClick={() => onChange(offset + limit)}
          disabled={to >= total}
          className="rounded-lg px-3 py-1.5 text-sm font-medium text-ink-600 ring-1 ring-inset ring-ink-100 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
