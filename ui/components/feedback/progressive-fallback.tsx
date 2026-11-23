import { PageHeader } from "@/components/page-header";
import { PageContainer } from "@/components/layout/page-container";
import { ListSkeleton, MetricSkeleton } from "@/components/feedback/loading-skeletons";

type ProgressiveFallbackProps = {
  title: string;
  description?: string;
  /** wide | default page container */
  wide?: boolean;
  metrics?: boolean;
};

/**
 * Suspense / progressive loading chrome: keeps PageHeader mounted and
 * skeletons only the content region (Documentation Center pattern).
 */
export function ProgressiveFallback({
  title,
  description = "Loading…",
  wide,
  metrics = true,
}: ProgressiveFallbackProps) {
  return (
    <PageContainer variant={wide ? "wide" : "constrained"} className="space-y-6">
      <PageHeader title={title} description={description} />
      {metrics ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <MetricSkeleton key={i} />
          ))}
        </div>
      ) : null}
      <ListSkeleton rows={6} />
    </PageContainer>
  );
}
