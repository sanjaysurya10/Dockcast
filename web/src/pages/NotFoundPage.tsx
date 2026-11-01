import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <Link to="/" className="text-brand-ink underline">
        Go to the station list
      </Link>
    </div>
  );
}
