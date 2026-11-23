import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { ReviewsView } from "@/features/reviews/reviews-view";

export const metadata = { title: "Reviews" };

export default function ReviewsPage() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="Reviews"
          description="AI-assisted code review history and detailed findings."
        />
      }
    >
      <ReviewsView />
    </Suspense>
  );
}
