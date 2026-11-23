import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";

export type Organization = {
  id: string;
  name: string;
  slug: string;
  description?: string;
  is_default?: boolean;
  branding?: Record<string, unknown>;
  settings?: Record<string, unknown>;
  counts?: { teams: number; members: number; repositories: number };
};

export type OrgTeam = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description?: string;
  member_ids?: string[];
  members?: { member_id: string; team_role: string }[];
  admins?: string[];
  repository_ids?: string[];
};

export type OrgMember = {
  id: string;
  organization_id: string;
  email: string;
  display_name: string;
  role: string;
  status: string;
  is_active?: boolean;
  permissions?: string[];
};

export type OrgRepository = {
  id: string;
  organization_id: string;
  repository_root_path: string;
  repository_name: string;
  nickname?: string | null;
  description?: string;
};

export type OrgDashboard = {
  organization: Organization;
  counts: { repositories: number; developers: number; teams: number };
  open_reviews: number;
  open_recommendations: number;
  branch_health: number | null;
  rule_violations: number;
  patch_success_pct: number | null;
  review_success_pct: number | null;
  repositories: OrgRepository[];
  teams: OrgTeam[];
  members: OrgMember[];
  recent_activity: unknown[];
};

export function fetchOrganizations(options: ApiClientOptions = {}) {
  return apiRequest<Organization[]>(endpoints.organizations, options);
}

export function fetchOrganization(id: string, options: ApiClientOptions = {}) {
  return apiRequest<Organization>(endpoints.organization(id), options);
}

export function createOrganization(
  body: { name: string; description?: string; slug?: string },
  options: ApiClientOptions = {},
) {
  return apiRequest<Organization>(endpoints.organizations, {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateOrganization(
  id: string,
  body: {
    name?: string;
    description?: string;
    settings?: Record<string, unknown>;
    branding?: Record<string, unknown>;
  },
  options: ApiClientOptions = {},
) {
  return apiRequest<Organization>(endpoints.organization(id), {
    ...options,
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function fetchOrganizationDashboard(
  id: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgDashboard>(endpoints.organizationDashboard(id), options);
}

export function fetchOrganizationTeams(
  orgId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgTeam[]>(endpoints.organizationTeams(orgId), options);
}

export function createOrganizationTeam(
  orgId: string,
  body: { name: string; description?: string; slug?: string },
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgTeam>(endpoints.organizationTeams(orgId), {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteOrganizationTeam(
  orgId: string,
  teamId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<{ deleted: boolean }>(
    endpoints.organizationTeam(orgId, teamId),
    { ...options, method: "DELETE" },
  );
}

export function addOrganizationTeamMember(
  orgId: string,
  teamId: string,
  body: { member_id: string; team_role?: string },
  options: ApiClientOptions = {},
) {
  return apiRequest<{ member_id: string; team_role: string }>(
    endpoints.organizationTeamMembers(orgId, teamId),
    {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function removeOrganizationTeamMember(
  orgId: string,
  teamId: string,
  memberId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<{ deleted: boolean }>(
    endpoints.organizationTeamMember(orgId, teamId, memberId),
    { ...options, method: "DELETE" },
  );
}

export function assignOrganizationTeamRepository(
  orgId: string,
  teamId: string,
  organizationRepositoryId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<{
    id: string;
    team_id: string;
    organization_repository_id: string;
  }>(endpoints.organizationTeamRepositories(orgId, teamId), {
    ...options,
    method: "POST",
    body: JSON.stringify({
      organization_repository_id: organizationRepositoryId,
    }),
  });
}

export function unassignOrganizationTeamRepository(
  orgId: string,
  teamId: string,
  organizationRepositoryId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<{ deleted: boolean }>(
    endpoints.organizationTeamRepository(orgId, teamId, organizationRepositoryId),
    { ...options, method: "DELETE" },
  );
}

export function fetchOrganizationMembers(
  orgId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgMember[]>(endpoints.organizationMembers(orgId), options);
}

export function inviteOrganizationMember(
  orgId: string,
  body: {
    email: string;
    role?: string;
    display_name?: string;
    team_ids?: string[];
  },
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgMember>(endpoints.organizationMembers(orgId), {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateOrganizationMember(
  orgId: string,
  memberId: string,
  body: { role?: string; display_name?: string; status?: string; is_active?: boolean },
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgMember>(endpoints.organizationMember(orgId, memberId), {
    ...options,
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function fetchOrganizationRepositories(
  orgId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgRepository[]>(
    endpoints.organizationRepositories(orgId),
    options,
  );
}

export function addOrganizationRepository(
  orgId: string,
  body: {
    root_path: string;
    name?: string;
    nickname?: string;
    team_ids?: string[];
  },
  options: ApiClientOptions = {},
) {
  return apiRequest<OrgRepository>(endpoints.organizationRepositories(orgId), {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function removeOrganizationRepository(
  orgId: string,
  repositoryId: string,
  options: ApiClientOptions = {},
) {
  return apiRequest<{ deleted: boolean }>(
    endpoints.organizationRepository(orgId, repositoryId),
    { ...options, method: "DELETE" },
  );
}

export function fetchRolesCatalog(options: ApiClientOptions = {}) {
  return apiRequest<{
    roles: { id: string; name: string; permissions: string[] }[];
    permissions: string[];
    team_roles: string[];
  }>(endpoints.organizationRoles, options);
}
