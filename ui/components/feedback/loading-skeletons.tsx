import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function PageSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-6", className)}>
      <div className="space-y-2">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <MetricSkeleton key={i} />
        ))}
      </div>
      <ListSkeleton rows={5} />
    </div>
  );
}

export function MetricSkeleton() {
  return (
    <div className="rounded-lg border p-4">
      <Skeleton className="mb-3 h-3 w-20" />
      <Skeleton className="h-7 w-16" />
      <Skeleton className="mt-2 h-3 w-28" />
    </div>
  );
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 rounded-lg border p-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function CardGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="space-y-2 rounded-lg border p-4">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      ))}
    </div>
  );
}
