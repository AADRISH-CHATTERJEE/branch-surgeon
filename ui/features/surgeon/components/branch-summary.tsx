import { StatusBadge } from "@/components/data-display/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { shortSha } from "@/lib/format";
import type { BranchSurgeonWorkspace } from "@/services/surgeon";

type BranchSummaryProps = {
  branch?: BranchSurgeonWorkspace["branch"] | null;
  surgeryScore?: number | null;
};

export function BranchSummary({ branch, surgeryScore }: BranchSummaryProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Branch Summary</CardTitle>
          {branch?.name ? <StatusBadge label={branch.name} tone="info" /> : null}
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-sm">
          <Field label="Branch" value={branch?.name} />
          <Field label="Base branch" value={branch?.base_branch} />
          <Field label="Repository" value={branch?.repository} />
          <Field label="HEAD" value={shortSha(branch?.head_sha)} mono />
          <Field label="Commits" value={formatNum(branch?.commits)} />
          <Field label="Changed files" value={formatNum(branch?.changed_files)} />
          <Field label="Insertions" value={formatNum(branch?.insertions)} />
          <Field label="Deletions" value={formatNum(branch?.deletions)} />
          <Field
            label="Surgery Score"
            value={surgeryScore != null ? String(surgeryScore) : "—"}
          />
        </dl>
      </CardContent>
    </Card>
  );
}

function formatNum(value?: number | null) {
  if (value == null) return "—";
  return String(value);
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-2xs font-medium uppercase text-muted-foreground">{label}</dt>
      <dd className={`mt-1 font-medium ${mono ? "font-mono text-xs" : ""}`}>
        {value || "—"}
      </dd>
    </div>
  );
}
