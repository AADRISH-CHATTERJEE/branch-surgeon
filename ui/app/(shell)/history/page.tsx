import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { HistoryView } from "@/features/history/history-view";

export const metadata = { title: "History" };

export default function HistoryPage() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="History"
          description="Analysis results memory — searchable timeline of Refactory runs."
        />
      }
    >
      <HistoryView />
    </Suspense>
  );
}
