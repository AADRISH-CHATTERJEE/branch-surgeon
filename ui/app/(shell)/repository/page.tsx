import { Suspense } from "react";

import { ProgressiveFallback } from "@/components/feedback/progressive-fallback";
import { RepositoryExplorer } from "@/features/repository/repository-explorer";

export const metadata = { title: "Repository" };

export default function RepositoryPage() {
  return (
    <Suspense fallback={<ProgressiveFallback title="Repository" description="Indexed files, symbols, and imports from the Local API." />}>
      <RepositoryExplorer />
    </Suspense>
  );
}
