"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { DEFAULT_PREFERENCES, loadPreferences } from "@/lib/preferences";

/** Root landing respects Settings → Appearance → Default landing page. */
export default function HomePage() {
  const router = useRouter();

  React.useEffect(() => {
    const landing = loadPreferences().landingPage || DEFAULT_PREFERENCES.landingPage;
    router.replace(landing);
  }, [router]);

  return (
    <div className="flex min-h-svh items-center justify-center text-sm text-muted-foreground">
      Opening workspace…
    </div>
  );
}
