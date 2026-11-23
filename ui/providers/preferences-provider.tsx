"use client";

import * as React from "react";

import {
  applyDocumentPreferences,
  DEFAULT_PREFERENCES,
  loadPreferences,
  savePreferences,
  type UiPreferences,
} from "@/lib/preferences";

type PreferencesContextValue = {
  preferences: UiPreferences;
  setPreferences: (next: UiPreferences | ((prev: UiPreferences) => UiPreferences)) => void;
  updatePreference: <K extends keyof UiPreferences>(key: K, value: UiPreferences[K]) => void;
  resetPreferences: () => void;
};

const PreferencesContext = React.createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [preferences, setPreferencesState] = React.useState<UiPreferences>(() =>
    typeof window === "undefined" ? DEFAULT_PREFERENCES : loadPreferences(),
  );

  React.useLayoutEffect(() => {
    applyDocumentPreferences(preferences);
  }, [preferences]);

  const setPreferences = React.useCallback(
    (next: UiPreferences | ((prev: UiPreferences) => UiPreferences)) => {
      setPreferencesState((prev) => {
        const resolved = typeof next === "function" ? next(prev) : next;
        savePreferences(resolved);
        return resolved;
      });
    },
    [],
  );

  const updatePreference = React.useCallback(
    <K extends keyof UiPreferences>(key: K, value: UiPreferences[K]) => {
      setPreferences((prev) => ({ ...prev, [key]: value }));
    },
    [setPreferences],
  );

  const resetPreferences = React.useCallback(() => {
    setPreferences({ ...DEFAULT_PREFERENCES });
  }, [setPreferences]);

  const value = React.useMemo(
    () => ({ preferences, setPreferences, updatePreference, resetPreferences }),
    [preferences, setPreferences, updatePreference, resetPreferences],
  );

  return (
    <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
  );
}

export function usePreferences() {
  const ctx = React.useContext(PreferencesContext);
  if (!ctx) {
    throw new Error("usePreferences must be used within PreferencesProvider");
  }
  return ctx;
}
