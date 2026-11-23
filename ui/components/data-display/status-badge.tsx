import { Badge } from "@/components/ui/badge";
import { toneClass, toneFromLabel, type StatusTone } from "@/lib/severity";
import { cn } from "@/lib/utils";

type StatusBadgeProps = {
  label: string;
  tone?: StatusTone;
  className?: string;
};

export function StatusBadge({ label, tone, className }: StatusBadgeProps) {
  const resolved = tone ?? toneFromLabel(label);
  return (
    <Badge
      variant="outline"
      className={cn("font-medium capitalize", toneClass(resolved), className)}
    >
      {label}
    </Badge>
  );
}
