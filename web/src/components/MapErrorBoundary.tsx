import { Component, type ReactNode } from "react";

interface State {
  failed: boolean;
}

/** If the map cannot start (no WebGL, style unreachable), the station list still works. */
export class MapErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div role="alert" className="flex h-full items-center justify-center p-6 text-center">
          <p className="text-muted">
            The map could not start in this browser. Use the station search and at-risk list.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
