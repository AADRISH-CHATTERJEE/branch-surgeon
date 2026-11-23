import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { ActivityView } from "@/features/activity/activity-view";

export const metadata = { title: "Activity" };

export default function ActivityPage() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="Activity"
          description="Analysis runs and local workspace timeline."
          metrics={false}
        />
      }
    >
      <ActivityView />
    </Suspense>
  );
}
