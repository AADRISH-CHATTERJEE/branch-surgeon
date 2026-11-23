"use client";

import * as React from "react";

import { useBackKeyboardShortcut } from "@/components/navigation/back-button";

const BackNavContext = React.createContext({ chromeProvidesBack: false });

export function useBackNav() {
  return React.useContext(BackNavContext);
}

/** Shell chrome already renders Back before breadcrumbs — PageHeader skips duplicate. */
export function BackNavProvider({
  children,
  chromeProvidesBack = true,
}: {
  children: React.ReactNode;
  chromeProvidesBack?: boolean;
}) {
  useBackKeyboardShortcut(true);
  return (
    <BackNavContext.Provider value={{ chromeProvidesBack }}>
      {children}
    </BackNavContext.Provider>
  );
}
