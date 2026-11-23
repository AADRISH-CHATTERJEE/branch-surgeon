"use client";

import { toast } from "sonner";

import { loadPreferences } from "@/lib/preferences";

/** Preference-aware toast helpers (duration + category filters). */
export const appToast = {
  success(message: string, description?: string) {
    const prefs = loadPreferences();
    if (!prefs.toastSuccess) return;
    toast.success(message, { description, duration: prefs.toastDurationMs });
  },
  warning(message: string, description?: string) {
    const prefs = loadPreferences();
    if (!prefs.toastWarnings) return;
    toast.warning(message, { description, duration: prefs.toastDurationMs });
  },
  error(message: string, description?: string) {
    const prefs = loadPreferences();
    if (!prefs.toastErrors) return;
    toast.error(message, { description, duration: prefs.toastDurationMs });
  },
  message(message: string, description?: string) {
    const prefs = loadPreferences();
    toast.message(message, { description, duration: prefs.toastDurationMs });
  },
  info(message: string, description?: string) {
    const prefs = loadPreferences();
    toast.info(message, { description, duration: prefs.toastDurationMs });
  },
};
