"use client";

import Link from "next/link";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EmptyState } from "@/components/feedback/empty-state";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useApiOptions } from "@/hooks/use-api-options";
import { useOrgContext } from "@/providers/org-context";
import { useRepoContext } from "@/providers/repo-context";
import { invalidateAnalysisMemory } from "@/queries/invalidate-analysis-memory";
import {
  addOrganizationRepository,
  createOrganization,
  fetchOrganizationRepositories,
  fetchRolesCatalog,
  removeOrganizationRepository,
  updateOrganization,
  type Organization,
} from "@/services/organizations";

function GeneralBrandingForm({
  organization,
  organizationId,
  onCreated,
}: {
  organization: Organization;
  organizationId: string;
  onCreated: (id: string) => void;
}) {
  const opts = useApiOptions();
  const { repoRoot } = useRepoContext();
  const qc = useQueryClient();
  const branding = (organization.branding || organization.settings || {}) as {
    primary_color?: string;
  };
  const [name, setName] = React.useState(organization.name);
  const [description, setDescription] = React.useState(
    organization.description ?? "",
  );
  const [primaryColor, setPrimaryColor] = React.useState(
    branding.primary_color || "#0f766e",
  );
  const [newOrgName, setNewOrgName] = React.useState("");

  const saveGeneral = useMutation({
    mutationFn: () =>
      updateOrganization(
        organizationId,
        {
          name,
          description,
          branding: { primary_color: primaryColor },
        },
        opts,
      ),
    onSuccess: () => {
      toast.success("Organization updated");
      void qc.invalidateQueries({ queryKey: ["organizations"] });
      invalidateAnalysisMemory(qc, repoRoot ?? "default");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const createOrg = useMutation({
    mutationFn: () => createOrganization({ name: newOrgName }, opts),
    onSuccess: (org) => {
      toast.success("Organization created");
      setNewOrgName("");
      onCreated(org.id);
      void qc.invalidateQueries({ queryKey: ["organizations"] });
      invalidateAnalysisMemory(qc, repoRoot ?? "default");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <>
      <TabsContent value="general" className="mt-4 max-w-xl space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="org-name">Name</Label>
          <Input id="org-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="org-desc">Description</Label>
          <Textarea
            id="org-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <Button onClick={() => saveGeneral.mutate()} disabled={saveGeneral.isPending}>
          Save
        </Button>

        <div className="border-t pt-6">
          <h3 className="mb-2 text-sm font-semibold">Create organization</h3>
          <div className="flex gap-2">
            <Input
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              placeholder="Acme Corp"
            />
            <Button
              variant="outline"
              disabled={!newOrgName.trim() || createOrg.isPending}
              onClick={() => createOrg.mutate()}
            >
              Create
            </Button>
          </div>
        </div>
      </TabsContent>

      <TabsContent value="branding" className="mt-4 max-w-md space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="brand-color">Primary color</Label>
          <Input
            id="brand-color"
            type="color"
            value={primaryColor}
            onChange={(e) => setPrimaryColor(e.target.value)}
          />
        </div>
        <Button onClick={() => saveGeneral.mutate()}>Save branding</Button>
      </TabsContent>
    </>
  );
}

export function OrganizationSettingsView() {
  const { organizationId, organization, setOrganizationId, selectRepository } =
    useOrgContext();
  const { repoRoot } = useRepoContext();
  const opts = useApiOptions();
  const qc = useQueryClient();
  const [repoPath, setRepoPath] = React.useState(repoRoot ?? "");

  const repos = useQuery({
    queryKey: ["org-repos-settings", organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationRepositories(organizationId!, { ...opts, signal }),
    enabled: opts.hydrated && Boolean(organizationId),
  });

  const roles = useQuery({
    queryKey: ["org-roles"],
    queryFn: ({ signal }) => fetchRolesCatalog({ ...opts, signal }),
    enabled: opts.hydrated,
  });

  const addRepo = useMutation({
    mutationFn: () =>
      addOrganizationRepository(
        organizationId!,
        { root_path: repoPath },
        opts,
      ),
    onSuccess: (link) => {
      toast.success("Repository linked");
      selectRepository(link.repository_root_path);
      void qc.invalidateQueries({ queryKey: ["org-repos"] });
      void qc.invalidateQueries({ queryKey: ["org-repos-settings"] });
      void qc.invalidateQueries({ queryKey: ["org-dashboard"] });
      invalidateAnalysisMemory(qc, repoRoot ?? "default");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const removeRepo = useMutation({
    mutationFn: (id: string) =>
      removeOrganizationRepository(organizationId!, id, opts),
    onSuccess: () => {
      toast.success("Repository unlinked");
      void qc.invalidateQueries({ queryKey: ["org-repos"] });
      void qc.invalidateQueries({ queryKey: ["org-repos-settings"] });
      invalidateAnalysisMemory(qc, repoRoot ?? "default");
    },
  });

  if (!organizationId || !organization) {
    return (
      <PageContainer>
        <EmptyState title="Select an organization" description="Settings are scoped per org." />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Organization settings"
        description="General, branding, repositories, rules, permissions, audit, API keys, integrations."
      />

      <Tabs defaultValue="general" className="mt-4">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="branding">Branding</TabsTrigger>
          <TabsTrigger value="repositories">Repositories</TabsTrigger>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="permissions">Permissions</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
          <TabsTrigger value="api-keys">API Keys</TabsTrigger>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
        </TabsList>

        <GeneralBrandingForm
          key={organization.id}
          organization={organization}
          organizationId={organizationId}
          onCreated={setOrganizationId}
        />

        <TabsContent value="repositories" className="mt-4 max-w-2xl space-y-4">
          <div className="flex flex-wrap gap-2">
            <Input
              className="min-w-[16rem] flex-1 font-mono text-xs"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="C:\\path\\to\\repo"
            />
            <Button
              disabled={!repoPath.trim() || addRepo.isPending}
              onClick={() => addRepo.mutate()}
            >
              Link repository
            </Button>
          </div>
          <ul className="space-y-2 text-sm">
            {(repos.data ?? []).map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2"
              >
                <div>
                  <div className="font-medium">{r.repository_name}</div>
                  <div className="font-mono text-2xs text-muted-foreground">
                    {r.repository_root_path}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => selectRepository(r.repository_root_path)}
                  >
                    Switch
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => removeRepo.mutate(r.id)}
                  >
                    Unlink
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </TabsContent>

        <TabsContent value="rules" className="mt-4 space-y-2 text-sm">
          <p className="text-muted-foreground">
            Rule precedence: Built-in → Organization → Team → Repository (
            <code className="text-xs">.refactory/rules.yaml</code>).
          </p>
          <Button asChild variant="outline" size="sm">
            <Link href="/rules">Open Rules workspace</Link>
          </Button>
        </TabsContent>

        <TabsContent value="permissions" className="mt-4 space-y-3 text-sm">
          <p className="text-muted-foreground">
            Local RBAC profiles (no login). Soft checks only until Enterprise auth.
          </p>
          <ul className="space-y-2">
            {(roles.data?.roles ?? []).map((r) => (
              <li key={r.id} className="rounded-md border px-3 py-2">
                <div className="font-medium capitalize">{r.name}</div>
                <div className="text-2xs text-muted-foreground">
                  {r.permissions.join(", ")}
                </div>
              </li>
            ))}
          </ul>
        </TabsContent>

        <TabsContent value="audit" className="mt-4 text-sm text-muted-foreground">
          Organization audit trail uses local activity + rule audits. SSO audit
          exports belong to Enterprise.
        </TabsContent>

        <TabsContent value="api-keys" className="mt-4 text-sm text-muted-foreground">
          API keys are stored in organization settings stubs only. No remote auth
          service in this phase.
        </TabsContent>

        <TabsContent value="integrations" className="mt-4 text-sm text-muted-foreground">
          Integrations (GitHub App, Slack, etc.) remain out of scope for Local.
        </TabsContent>
      </Tabs>
    </PageContainer>
  );
}
