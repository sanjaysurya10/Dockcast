import { ApiError } from "@/api/client";

export function Loading({ label }: { label: string }) {
  return (
    <p role="status" className="text-muted">
      Loading {label}…
    </p>
  );
}

export function ErrorMessage({ error, label }: { error: unknown; label: string }) {
  const detail =
    error instanceof ApiError
      ? `${error.message || error.code} (HTTP ${error.status})`
      : "The API could not be reached.";
  return (
    <div role="alert" className="rounded-card border border-line bg-surface p-4">
      <p className="font-medium">Could not load {label}.</p>
      <p className="text-sm text-muted">{detail}</p>
    </div>
  );
}
