import { cn } from "@/lib/utils";

type PageContainerProps = {
  children: React.ReactNode;
  /** constrained = max-w-7xl (default); wide = full workspace width */
  variant?: "constrained" | "wide";
  className?: string;
};

export function PageContainer({
  children,
  variant = "constrained",
  className,
}: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-4 py-6 sm:px-6",
        variant === "constrained" ? "max-w-7xl" : "max-w-[1600px]",
        className,
      )}
    >
      {children}
    </div>
  );
}
