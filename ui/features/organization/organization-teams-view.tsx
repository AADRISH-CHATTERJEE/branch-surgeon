"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EmptyState } from "@/components/feedback/empty-state";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  addOrganizationTeamMember,
  assignOrganizationTeamRepository,
  createOrganizationTeam,
  deleteOrganizationTeam,
  fetchOrganizationMembers,
  fetchOrganizationRepositories,
  fetchOrganizationTeams,
  removeOrganizationTeamMember,
  unassignOrganizationTeamRepository,
} from "@/services/organizations";

type ConfirmState =
  | null
  | {
      kind: "remove-member";
      teamId: string;
      teamName: string;
      memberId: string;
      memberLabel: string;
    }
  | {
      kind: "delete-team";
      teamId: string;
      teamName: string;
    };

export function OrganizationTeamsView() {
  const { organizationId, setTeamId, teamId } = useOrgContext();
  const { repoRoot } = useRepoContext();
  const opts = useApiOptions();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [addMemberByTeam, setAddMemberByTeam] = React.useState<
    Record<string, string>
  >({});
  const [addRepoByTeam, setAddRepoByTeam] = React.useState<Record<string, string>>(
    {},
  );
  const [confirm, setConfirm] = React.useState<ConfirmState>(null);

  const teams = useQuery({
    queryKey: ["org-teams-page", organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationTeams(organizationId!, { ...opts, signal }),
    enabled: opts.hydrated && Boolean(organizationId),
  });

  const members = useQuery({
    queryKey: ["org-members-page", organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationMembers(organizationId!, { ...opts, signal }),
    enabled: opts.hydrated && Boolean(organizationId),
  });

  const repos = useQuery({
    queryKey: ["org-repos-settings", organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationRepositories(organizationId!, { ...opts, signal }),
    enabled: opts.hydrated && Boolean(organizationId),
  });

  const invalidateTeams = () => {
    void qc.invalidateQueries({ queryKey: ["org-teams"] });
    void qc.invalidateQueries({ queryKey: ["org-teams-page"] });
    void qc.invalidateQueries({ queryKey: ["org-dashboard"] });
    void qc.invalidateQueries({ queryKey: ["org-repos"] });
    void qc.invalidateQueries({ queryKey: ["org-repos-settings"] });
    invalidateAnalysisMemory(qc, repoRoot ?? "default");
  };

  const createTeam = useMutation({
    mutationFn: () =>
      createOrganizationTeam(organizationId!, { name }, opts),
    onSuccess: () => {
      toast.success("Team created");
      setName("");
      invalidateTeams();
    },
    onError: (err: Error) => toast.error(err.message || "Unable to create team"),
  });

  const removeMember = useMutation({
    mutationFn: ({
      teamId: tid,
      memberId,
    }: {
      teamId: string;
      memberId: string;
    }) => removeOrganizationTeamMember(organizationId!, tid, memberId, opts),
    onSuccess: () => {
      toast.success("Removed from team");
      setConfirm(null);
      invalidateTeams();
    },
    onError: (err: Error) =>
      toast.error(err.message || "Unable to remove team member"),
  });

  const deleteTeam = useMutation({
    mutationFn: (tid: string) =>
      deleteOrganizationTeam(organizationId!, tid, opts),
    onSuccess: (_data, tid) => {
      toast.success("Team deleted");
      if (teamId === tid) setTeamId(null);
      setConfirm(null);
      invalidateTeams();
    },
    onError: (err: Error) => toast.error(err.message || "Unable to delete team"),
  });

  const addMember = useMutation({
    mutationFn: ({
      teamId: tid,
      memberId,
    }: {
      teamId: string;
      memberId: string;
    }) =>
      addOrganizationTeamMember(
        organizationId!,
        tid,
        { member_id: memberId },
        opts,
      ),
    onSuccess: (_data, vars) => {
      toast.success("Added to team");
      setAddMemberByTeam((prev) => ({ ...prev, [vars.teamId]: "" }));
      invalidateTeams();
    },
    onError: (err: Error) =>
      toast.error(err.message || "Unable to add team member"),
  });

  const assignRepo = useMutation({
    mutationFn: ({
      teamId: tid,
      repositoryId,
    }: {
      teamId: string;
      repositoryId: string;
    }) =>
      assignOrganizationTeamRepository(organizationId!, tid, repositoryId, opts),
    onSuccess: (_data, vars) => {
      toast.success("Repository linked to team");
      setAddRepoByTeam((prev) => ({ ...prev, [vars.teamId]: "" }));
      invalidateTeams();
    },
    onError: (err: Error) =>
      toast.error(err.message || "Unable to link repository"),
  });

  const unassignRepo = useMutation({
    mutationFn: ({
      teamId: tid,
      repositoryId,
    }: {
      teamId: string;
      repositoryId: string;
    }) =>
      unassignOrganizationTeamRepository(
        organizationId!,
        tid,
        repositoryId,
        opts,
      ),
    onSuccess: () => {
      toast.success("Repository unlinked from team");
      invalidateTeams();
    },
    onError: (err: Error) =>
      toast.error(err.message || "Unable to unlink repository"),
  });

  const confirmBusy = removeMember.isPending || deleteTeam.isPending;

  const runConfirmedAction = () => {
    if (!confirm) return;
    if (confirm.kind === "remove-member") {
      removeMember.mutate({
        teamId: confirm.teamId,
        memberId: confirm.memberId,
      });
      return;
    }
    deleteTeam.mutate(confirm.teamId);
  };

  if (!organizationId) {
    return (
      <PageContainer>
        <EmptyState title="Select an organization" description="Teams are scoped per org." />
      </PageContainer>
    );
  }

  const memberLabel = (id: string) => {
    const m = members.data?.find((row) => row.id === id);
    if (!m) return id.slice(0, 8);
    return m.display_name || m.email || id.slice(0, 8);
  };

  const memberEmail = (id: string) =>
    members.data?.find((row) => row.id === id)?.email ?? "";

  const repoLabel = (id: string) => {
    const r = repos.data?.find((row) => row.id === id);
    if (!r) return id.slice(0, 8);
    return r.nickname || r.repository_name || r.repository_root_path;
  };

  return (
    <PageContainer>
      <PageHeader
        title="Teams"
        description="Manage team members and linked repositories. Invite users on Members (optionally with a team), or add them here."
      />

      <form
        className="mb-8 flex max-w-lg flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) createTeam.mutate();
        }}
      >
        <div className="min-w-[12rem] flex-1 space-y-1.5">
          <Label htmlFor="team-name">New team</Label>
          <Input
            id="team-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Backend Team"
          />
        </div>
        <Button type="submit" disabled={!name.trim() || createTeam.isPending}>
          Create
        </Button>
      </form>

      <ul className="space-y-3">
        {(teams.data ?? []).map((team) => {
          const memberIds = team.member_ids ?? [];
          const repoIds = team.repository_ids ?? [];
          const availableMembers = (members.data ?? []).filter(
            (m) => !memberIds.includes(m.id),
          );
          const availableRepos = (repos.data ?? []).filter(
            (r) => !repoIds.includes(r.id),
          );
          const selectedAdd = addMemberByTeam[team.id] ?? "";
          const selectedRepo = addRepoByTeam[team.id] ?? "";

          return (
            <li key={team.id} className="rounded-md border p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 className="font-medium">{team.name}</h3>
                  <p className="text-sm text-muted-foreground">
                    {team.description || `Slug: ${team.slug}`}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant={teamId === team.id ? "default" : "outline"}
                    onClick={() => setTeamId(teamId === team.id ? null : team.id)}
                  >
                    {teamId === team.id ? "Active rule scope" : "Use for rules"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-destructive hover:text-destructive"
                    onClick={() =>
                      setConfirm({
                        kind: "delete-team",
                        teamId: team.id,
                        teamName: team.name,
                      })
                    }
                  >
                    Delete team
                  </Button>
                </div>
              </div>

              <div className="mt-4 space-y-2">
                <div className="text-xs text-muted-foreground">Members</div>
                {memberIds.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No members on this team yet. Add an org member below (or invite
                    with this team selected on Members).
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {memberIds.map((mid) => (
                      <li
                        key={mid}
                        className="flex items-center justify-between gap-3 rounded-sm border px-2 py-1.5"
                      >
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">
                            {memberLabel(mid)}
                            {(team.admins ?? []).includes(mid) ? (
                              <span className="ml-2 text-xs font-normal text-muted-foreground">
                                lead
                              </span>
                            ) : null}
                          </div>
                          {memberEmail(mid) ? (
                            <div className="truncate text-xs text-muted-foreground">
                              {memberEmail(mid)}
                            </div>
                          ) : null}
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="shrink-0 text-destructive hover:text-destructive"
                          onClick={() =>
                            setConfirm({
                              kind: "remove-member",
                              teamId: team.id,
                              teamName: team.name,
                              memberId: mid,
                              memberLabel: memberLabel(mid),
                            })
                          }
                        >
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}

                {availableMembers.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Select
                      value={selectedAdd || undefined}
                      onValueChange={(value) =>
                        setAddMemberByTeam((prev) => ({
                          ...prev,
                          [team.id]: value,
                        }))
                      }
                    >
                      <SelectTrigger className="w-[16rem]">
                        <SelectValue placeholder="Add member…" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableMembers.map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.display_name || m.email}
                            {m.email && m.display_name ? ` (${m.email})` : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={
                        !selectedAdd ||
                        (addMember.isPending &&
                          addMember.variables?.teamId === team.id)
                      }
                      onClick={() =>
                        addMember.mutate({
                          teamId: team.id,
                          memberId: selectedAdd,
                        })
                      }
                    >
                      Add
                    </Button>
                  </div>
                ) : memberIds.length > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    All organization members are already on this team.
                  </p>
                ) : null}
              </div>

              <div className="mt-4 space-y-2">
                <div className="text-xs text-muted-foreground">Repositories</div>
                {repoIds.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No repositories linked. Link an organization repository below
                    (add repos under Organization → Settings first).
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {repoIds.map((rid) => (
                      <li
                        key={rid}
                        className="flex items-center justify-between gap-3 rounded-sm border px-2 py-1.5"
                      >
                        <span className="truncate text-sm">{repoLabel(rid)}</span>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="shrink-0 text-destructive hover:text-destructive"
                          disabled={
                            unassignRepo.isPending &&
                            unassignRepo.variables?.teamId === team.id &&
                            unassignRepo.variables?.repositoryId === rid
                          }
                          onClick={() =>
                            unassignRepo.mutate({
                              teamId: team.id,
                              repositoryId: rid,
                            })
                          }
                        >
                          Unlink
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}

                {availableRepos.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Select
                      value={selectedRepo || undefined}
                      onValueChange={(value) =>
                        setAddRepoByTeam((prev) => ({
                          ...prev,
                          [team.id]: value,
                        }))
                      }
                    >
                      <SelectTrigger className="w-[16rem]">
                        <SelectValue placeholder="Link repository…" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableRepos.map((r) => (
                          <SelectItem key={r.id} value={r.id}>
                            {r.nickname || r.repository_name || r.repository_root_path}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={
                        !selectedRepo ||
                        (assignRepo.isPending &&
                          assignRepo.variables?.teamId === team.id)
                      }
                      onClick={() =>
                        assignRepo.mutate({
                          teamId: team.id,
                          repositoryId: selectedRepo,
                        })
                      }
                    >
                      Link
                    </Button>
                  </div>
                ) : (repos.data ?? []).length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No organization repositories yet. Add one in Settings.
                  </p>
                ) : null}
              </div>

              <div className="mt-3 text-sm">
                <div className="text-xs text-muted-foreground">Admins / leads</div>
                <div>
                  {(team.admins ?? []).map(memberLabel).join(", ") || "—"}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <Dialog
        open={confirm != null}
        onOpenChange={(open) => {
          if (!open && !confirmBusy) setConfirm(null);
        }}
      >
        <DialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            document
              .getElementById("main-content")
              ?.focus({ preventScroll: true });
            window.scrollTo(0, 0);
          }}
        >
          <DialogHeader>
            <DialogTitle>Are you sure?</DialogTitle>
            <DialogDescription>
              {confirm?.kind === "delete-team"
                ? `Delete team “${confirm.teamName}”? Members stay in the organization; team membership and repository links for this team are removed.`
                : confirm?.kind === "remove-member"
                  ? `Remove “${confirm.memberLabel}” from team “${confirm.teamName}”?`
                  : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={confirmBusy}
              onClick={() => setConfirm(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={confirmBusy}
              onClick={runConfirmedAction}
            >
              {confirmBusy
                ? "Working…"
                : confirm?.kind === "delete-team"
                  ? "Delete team"
                  : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
