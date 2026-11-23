"use client";

import * as React from "react";

import { ErrorState } from "@/components/feedback/error-state";

type Props = {
  children: React.ReactNode;
  fallbackTitle?: string;
};

type State = { error: Error | null };

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          title={this.props.fallbackTitle ?? "UI error"}
          description={this.state.error.message}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
