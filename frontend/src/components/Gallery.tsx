import { useState } from "react";

export function Gallery({ images, name }: { images: string[]; name: string }) {
  const [active, setActive] = useState(0);
  const [broken, setBroken] = useState<Set<number>>(new Set());

  const valid = images.filter((_, i) => !broken.has(i));

  if (images.length === 0) {
    return (
      <div className="flex aspect-[16/9] w-full items-center justify-center rounded-2xl bg-ink-100 text-ink-300">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    );
  }

  const activeIdx = Math.min(active, images.length - 1);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative aspect-[16/9] w-full overflow-hidden rounded-2xl bg-ink-100">
        <img
          src={images[activeIdx]}
          alt={name}
          className="h-full w-full object-cover"
          onError={() => setBroken((s) => new Set(s).add(activeIdx))}
        />
        {valid.length > 1 && (
          <span className="absolute bottom-3 right-3 rounded-full bg-ink-950/70 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm">
            {activeIdx + 1} / {images.length}
          </span>
        )}
      </div>
      {images.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {images.map((url, i) =>
            broken.has(i) ? null : (
              <button
                key={url + i}
                onClick={() => setActive(i)}
                className={`h-16 w-24 flex-shrink-0 overflow-hidden rounded-lg ring-2 transition ${
                  i === activeIdx ? "ring-ember-500" : "ring-transparent opacity-70 hover:opacity-100"
                }`}
              >
                <img
                  src={url}
                  alt=""
                  className="h-full w-full object-cover"
                  onError={() => setBroken((s) => new Set(s).add(i))}
                />
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}
