import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { RecommendationsView } from "@/features/recommendations/recommendations-view";

export const metadata = { title: "Recommendations" };

export default function RecommendationsPage() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="Recommendations"
          description="AI-generated engineering recommendations as an actionable backlog."
        />
      }
    >
      <RecommendationsView />
    </Suspense>
  );
}
