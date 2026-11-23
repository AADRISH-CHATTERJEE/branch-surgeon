"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EmptyState } from "@/components/feedback/empty-state";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useApiOptions } from "@/hooks/use-api-options";
import { useOrgContext } from "@/providers/org-context";
import { useRepoContext } from "@/providers/repo-context";
import { invalidateAnalysisMemory } from "@/queries/invalidate-analysis-memory";
import {
  fetchOrganizationMembers,
  fetchRolesCatalog,
  inviteOrganizationMember,
  updateOrganizationMember,
} from "@/services/organizations";

const ROLES = [
  "owner",
  "admin",
  "maintainer",
  "reviewer",
  "developer",
  "viewer",
] as const;

export function OrganizationMembersView() {
  const { organizationId, teams } = useOrgContext();
  const { repoRoot } = useRepoContext();
  const opts = useApiOptions();
  const qc = useQueryClient();
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<string>("developer");
  const [teamId, setTeamId] = React.useState<string>("");

  const members = useQuery({
    queryKey: ["org-members-page", organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationMembers(organizationId!, { ...opts, signal }),
    enabled: opts.hydrated && Boolean(organizationId),
  });

  const roles = useQuery({
    queryKey: ["org-roles"],
    queryFn: ({ signal }) => fetchRolesCatalog({ ...opts, signal }),
    enabled: opts.hydrated,
  });

  const invite = useMutation({
    mutationFn: () =>
      inviteOrganizationMember(
        organizationId!,
        {
          email,
          role,
          team_ids: teamId ? [teamId] : [],
        },
        opts,
      ),
    onSuccess: () => {
      toast.success("Member invited (local profile — no email sent)");
      setEmail("");
      void qc.invalidateQueries({ queryKey: ["org-members-page"] });
      void qc.invalidateQueries({ queryKey: ["org-members"] });
      void qc.invalidateQueries({ queryKey: ["org-teams"] });
      void qc.invalidateQueries({ queryKey: ["org-teams-page"] });
      void qc.invalidateQueries({ queryKey: ["org-dashboard"] });
      invalidateAnalysisMemory(qc, repoRoot ?? "default");
    },
    onError: (err: Error) => toast.error(err.message || "Invite failed"),
  });

  const activate = useMutation({
    mutationFn: (memberId: string) =>
      updateOrganizationMember(
        organizationId!,
        memberId,
        { status: "active" },
        opts,
      ),
    onSuccess: () => {
      toast.success("Member activated");
      void qc.invalidateQueries({ queryKey: ["org-members-page"] });
      invalidateAnalysisMemory(qc, repoRoot ?? "default");
    },
  });

  if (!organizationId) {
    return (
      <PageContainer>
        <EmptyState title="Select an organization" description="Members are scoped per org." />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Members"
        description="Invite users with a role and optional team. No SSO or email delivery."
      />

      <form
        className="mb-8 grid max-w-2xl gap-3 sm:grid-cols-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) invite.mutate();
        }}
      >
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="invite-email">Email</Label>
          <Input
            id="invite-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="dev@acme.local"
          />
        </div>
        <div className="space-y-1.5">
          <Label>Role</Label>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(roles.data?.roles.map((r) => r.id) ?? ROLES).map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Team</Label>
          <Select value={teamId || "__none"} onValueChange={(v) => setTeamId(v === "__none" ? "" : v)}>
            <SelectTrigger>
              <SelectValue placeholder="Optional" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none">None</SelectItem>
              {teams.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-end sm:col-span-4">
          <Button type="submit" disabled={!email.trim() || invite.isPending}>
            Invite user
          </Button>
        </div>
      </form>

      <ul className="space-y-2">
        {(members.data ?? []).map((m) => (
          <li
            key={m.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
          >
            <div>
              <div className="font-medium">{m.display_name}</div>
              <div className="text-muted-foreground">
                {m.email} · {m.role} · {m.status}
              </div>
            </div>
            {m.status === "invited" ? (
              <Button size="sm" variant="outline" onClick={() => activate.mutate(m.id)}>
                Activate
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </PageContainer>
  );
}
