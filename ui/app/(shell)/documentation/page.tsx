import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { DocumentationView } from "@/features/documentation/documentation-view";

export const metadata = { title: "Documentation" };

export default function DocumentationPage() {
  return (
    <Suspense
      fallback={
        <ProgressiveFallback
          title="Documentation"
          description="Product docs, guides, and Local API reference."
          wide
          metrics={false}
        />
      }
    >
      <DocumentationView />
    </Suspense>
  );
}
