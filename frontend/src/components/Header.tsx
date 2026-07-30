import { Link } from "react-router-dom";

export function Header() {
  return (
    <header className="sticky top-0 z-20 border-b border-ink-100 bg-ink-50/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center px-4 py-3.5 sm:px-6">
        <Link to="/app" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink-900 text-ember-400">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="flex flex-col leading-none">
            <span className="font-display text-[17px] font-semibold text-ink-900">Away Hotels</span>
            <span className="text-[11px] font-medium tracking-wide text-ink-400">Canonical Layer</span>
          </span>
        </Link>
        <div className="ml-auto flex items-center gap-4">
          <Link to="/" className="text-sm font-medium text-ink-500 hover:text-ink-900 transition">
            ← About this project
          </Link>
          <Link to="/app/admin" className="text-sm font-medium text-ink-600 hover:text-ink-900 transition">
            Admin Panel
          </Link>
        </div>
      </div>
    </header>
  );
}
