"use client";

import { Toaster } from "@/components/ui/sonner";
import { usePreferences } from "@/providers/preferences-provider";

export function AppToaster() {
  const { preferences } = usePreferences();
  return (
    <Toaster
      richColors
      closeButton
      position="bottom-right"
      duration={preferences.toastDurationMs}
    />
  );
}
