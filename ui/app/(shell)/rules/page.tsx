import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { RulesView } from "@/features/rules/rules-view";

export const metadata = { title: "Rules" };

export default function RulesPage() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="Rules"
          description="Company engineering rules and compliance checks."
        />
      }
    >
      <RulesView />
    </Suspense>
  );
}
