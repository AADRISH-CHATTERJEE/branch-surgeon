"use client";

import * as React from "react";

import { usePreferences } from "@/providers/preferences-provider";

type PreferMotionDivProps = {
  children?: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  initial?: unknown;
  animate?: unknown;
  transition?: unknown;
};

type MotionDivComponent = React.ComponentType<{
  children?: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  initial?: never;
  animate?: never;
  transition?: never;
}>;

/**
 * Framer Motion wrapper that becomes a plain `div` when Animations are OFF.
 * Loads framer-motion via a plain dynamic import (not next/dynamic) to avoid
 * React 19 "script tag while rendering" console errors.
 */
export function PreferMotionDiv({
  children,
  className,
  style,
  initial,
  animate,
  transition,
}: PreferMotionDivProps) {
  const { preferences } = usePreferences();
  const [MotionDiv, setMotionDiv] = React.useState<MotionDivComponent | null>(null);

  React.useEffect(() => {
    if (!preferences.animations) return;
    let cancelled = false;
    void import("./motion-div").then((m) => {
      if (!cancelled) setMotionDiv(() => m.MotionDiv as MotionDivComponent);
    });
    return () => {
      cancelled = true;
    };
  }, [preferences.animations]);

  if (!preferences.animations || !MotionDiv) {
    return (
      <div className={className} style={style}>
        {children}
      </div>
    );
  }

  return (
    <MotionDiv
      className={className}
      style={style}
      initial={initial as never}
      animate={animate as never}
      transition={transition as never}
    >
      {children}
    </MotionDiv>
  );
}

/** True when UI animations preference is enabled and OS allows motion. */
export function useAnimationsEnabled() {
  const { preferences } = usePreferences();
  const [reduceMotion, setReduceMotion] = React.useState(false);

  React.useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduceMotion(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  return preferences.animations && !reduceMotion;
}
