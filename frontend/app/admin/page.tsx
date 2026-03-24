"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/app/context/AuthContext";
import { UserPlus, ShieldCheck, Key, Trash2, PowerOff, Power } from "lucide-react";

const ROLE_LABELS: Record<string, string> = {
  operator: "Operator",
  shift_lead: "Shift Lead",
  engineer: "Engineer",
  viewer: "Viewer",
  tenant_admin: "Tenant Admin",
};

interface TenantUser {
  user_id: string;
  username: string;
  tenant_role: string;
  is_active: boolean;
  granted_at: string | null;
  granted_by: string | null;
}

// ---------------------------------------------------------------------------
// User row
// ---------------------------------------------------------------------------

function UserRow({
  user,
  assignableRoles,
  isAdmin,
  authFetch,
  tenantId,
  onRefresh,
}: {
  user: TenantUser;
  assignableRoles: string[];
  isAdmin: boolean;
  authFetch: (path: string, opts?: RequestInit) => Promise<Response>;
  tenantId: string;
  onRefresh: () => void;
}) {
  const [pendingRole, setPendingRole] = useState(user.tenant_role);
  const [roleBusy, setRoleBusy] = useState(false);
  const [showReset, setShowReset] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState("");
  const [resetSuccess, setResetSuccess] = useState(false);
  const [revokeConfirm, setRevokeConfirm] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [activeBusy, setActiveBusy] = useState(false);
  const [rowError, setRowError] = useState("");

  async function saveRole() {
    if (pendingRole === user.tenant_role) return;
    setRoleBusy(true);
    setRowError("");
    try {
      const res = await authFetch(`/api/v1/users/${user.user_id}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role: pendingRole }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error(b?.detail ?? `HTTP ${res.status}`);
      }
      onRefresh();
    } catch (e: any) {
      setRowError(e.message);
      setPendingRole(user.tenant_role);
    } finally {
      setRoleBusy(false);
    }
  }

  async function submitResetPassword(e: React.FormEvent) {
    e.preventDefault();
    setResetBusy(true);
    setResetError("");
    try {
      const res = await authFetch(
        `/api/v1/users/${user.user_id}/reset-password`,
        { method: "POST", body: JSON.stringify({ new_password: newPassword }) },
      );
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error(b?.detail ?? `HTTP ${res.status}`);
      }
      setShowReset(false);
      setNewPassword("");
      setResetSuccess(true);
      setTimeout(() => setResetSuccess(false), 3000);
    } catch (e: any) {
      setResetError(e.message);
    } finally {
      setResetBusy(false);
    }
  }

  async function confirmRevoke() {
    setRevokeBusy(true);
    setRowError("");
    try {
      const res = await authFetch(
        `/api/v1/users/${user.user_id}/access`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error(b?.detail ?? `HTTP ${res.status}`);
      }
      onRefresh();
    } catch (e: any) {
      setRowError(e.message);
      setRevokeConfirm(false);
    } finally {
      setRevokeBusy(false);
    }
  }

  async function toggleActive() {
    const path = user.is_active ? "deactivate" : "activate";
    setActiveBusy(true);
    setRowError("");
    try {
      const res = await authFetch(
        `/api/v1/users/${user.user_id}/${path}`,
        { method: "PATCH" },
      );
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error(b?.detail ?? `HTTP ${res.status}`);
      }
      onRefresh();
    } catch (e: any) {
      setRowError(e.message);
    } finally {
      setActiveBusy(false);
    }
  }

  const roleDirty = pendingRole !== user.tenant_role;

  return (
    <tr className="border-b border-cyan-900/30 hover:bg-white/5 transition-colors">
      <td className="px-4 py-3 text-white font-medium">
        {user.username}
        {!user.is_active && (
          <span className="ml-2 text-xs text-red-400 font-normal">(inactive)</span>
        )}
      </td>

      {/* Role select + save */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <select
            value={pendingRole}
            onChange={(e) => setPendingRole(e.target.value)}
            className="bg-[#06203b] border border-cyan-900/50 text-white text-sm rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-cyan-400"
          >
            {assignableRoles.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r] ?? r}
              </option>
            ))}
          </select>
          {roleDirty && (
            <button
              onClick={saveRole}
              disabled={roleBusy}
              className="text-xs px-2 py-1 rounded bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold disabled:opacity-50"
            >
              {roleBusy ? "..." : "Save"}
            </button>
          )}
        </div>
      </td>

      {/* Actions */}
      <td className="px-4 py-3">
        <div className="flex flex-wrap items-start gap-2">
          {/* Reset password */}
          <div>
            <button
              onClick={() => { setShowReset(!showReset); setResetError(""); setNewPassword(""); }}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-cyan-900/50 text-white/80 hover:text-white hover:border-cyan-700/50 transition-colors"
            >
              <Key className="w-3 h-3" /> Reset PW
            </button>
            {showReset && (
              <form onSubmit={submitResetPassword} className="mt-2 flex items-center gap-2">
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="New password (8+ chars)"
                  minLength={8}
                  required
                  autoComplete="new-password"
                  className="text-xs px-2 py-1 rounded bg-[#06203b] border border-cyan-900/50 text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-400 w-44"
                />
                <button
                  type="submit"
                  disabled={resetBusy}
                  className="text-xs px-2 py-1 rounded bg-violet-500 hover:bg-violet-400 text-white font-bold disabled:opacity-50"
                >
                  {resetBusy ? "..." : "Set"}
                </button>
                {resetError && (
                  <span className="text-xs text-red-400">{resetError}</span>
                )}
              </form>
            )}
            {resetSuccess && (
              <p className="mt-1 text-xs text-green-400">Password updated.</p>
            )}
          </div>

          {/* Revoke access */}
          {!revokeConfirm ? (
            <button
              onClick={() => setRevokeConfirm(true)}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-red-900/60 text-red-400 hover:text-red-300 hover:border-red-700/60 transition-colors"
            >
              <Trash2 className="w-3 h-3" /> Revoke
            </button>
          ) : (
            <div className="flex items-center gap-1">
              <span className="text-xs text-red-300">Sure?</span>
              <button
                onClick={confirmRevoke}
                disabled={revokeBusy}
                className="text-xs px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white font-bold disabled:opacity-50"
              >
                {revokeBusy ? "..." : "Yes"}
              </button>
              <button
                onClick={() => setRevokeConfirm(false)}
                className="text-xs px-2 py-1 rounded border border-cyan-900/50 text-white/60 hover:text-white"
              >
                No
              </button>
            </div>
          )}

          {/* Deactivate / Activate (admin:all only) */}
          {isAdmin && (
            <button
              onClick={toggleActive}
              disabled={activeBusy}
              className={`flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors disabled:opacity-50 ${
                user.is_active
                  ? "border-orange-900/60 text-orange-400 hover:text-orange-300 hover:border-orange-700/60"
                  : "border-green-900/60 text-green-400 hover:text-green-300 hover:border-green-700/60"
              }`}
            >
              {user.is_active ? (
                <><PowerOff className="w-3 h-3" /> Deactivate</>
              ) : (
                <><Power className="w-3 h-3" /> Activate</>
              )}
            </button>
          )}
        </div>

        {rowError && (
          <p className="mt-1 text-xs text-red-400">{rowError}</p>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminPage() {
  const { token, tenantId, tenantName, role, authFetch } = useAuth();
  const router = useRouter();

  const isAdmin = role === "admin";
  const isTenantAdmin = role === "tenant_admin";
  const canManage = isAdmin || isTenantAdmin;

  const assignableRoles = isAdmin
    ? ["operator", "shift_lead", "engineer", "viewer", "tenant_admin"]
    : ["operator", "shift_lead", "engineer", "viewer"];

  const [users, setUsers] = useState<TenantUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Create form state
  const [showCreate, setShowCreate] = useState(false);
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] = useState("operator");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [pageSuccess, setPageSuccess] = useState("");

  useEffect(() => {
    if (!canManage) {
      router.replace("/dashboard");
    }
  }, [canManage, router]);

  async function fetchUsers() {
    setLoading(true);
    setError("");
    try {
      const res = await authFetch("/api/v1/users");
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error(b?.detail ?? `HTTP ${res.status}`);
      }
      setUsers(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (canManage && token) fetchUsers();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, tenantId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateBusy(true);
    setCreateError("");
    try {
      const res = await authFetch("/api/v1/users", {
        method: "POST",
        body: JSON.stringify({
          username: createUsername,
          password: createPassword,
          role: createRole,
        }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error(b?.detail ?? `HTTP ${res.status}`);
      }
      setShowCreate(false);
      setPageSuccess(`User "${createUsername}" created successfully.`);
      setTimeout(() => setPageSuccess(""), 4000);
      setCreateUsername("");
      setCreatePassword("");
      setCreateRole("operator");
      fetchUsers();
    } catch (e: any) {
      setCreateError(e.message);
    } finally {
      setCreateBusy(false);
    }
  }

  if (!canManage) return null;

  return (
    <div className="min-h-screen bg-[#06203b] py-8 px-4 md:px-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-cyan-400" />
            User Management
          </h1>
          <p className="text-white/60 text-sm mt-1">
            {tenantName} — managing users for this tenant
          </p>
        </div>
        <button
          onClick={() => { setShowCreate(!showCreate); setCreateError(""); }}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold text-sm transition-colors"
        >
          <UserPlus className="w-4 h-4" />
          Add User
        </button>
      </div>

      {pageSuccess && (
        <div className="mb-4 p-3 rounded-lg bg-green-900/60 border border-green-700/40 text-green-300 text-sm">
          {pageSuccess}
        </div>
      )}

      {/* Create user panel */}
      {showCreate && (
        <div className="mb-6 bg-[#0a2d4a] rounded-xl border border-cyan-900/40 p-6">
          <h2 className="text-white font-semibold mb-4">New User</h2>
          <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-xs text-white/60 mb-1">Username</label>
              <input
                type="text"
                value={createUsername}
                onChange={(e) => setCreateUsername(e.target.value)}
                required
                placeholder="e.g. john.doe"
                className="px-3 py-2 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-400 w-48"
              />
            </div>
            <div>
              <label className="block text-xs text-white/60 mb-1">Password</label>
              <input
                type="password"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
                placeholder="Min 8 characters"
                className="px-3 py-2 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-400 w-48"
              />
            </div>
            <div>
              <label className="block text-xs text-white/60 mb-1">Role</label>
              <select
                value={createRole}
                onChange={(e) => setCreateRole(e.target.value)}
                className="px-3 py-2 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white text-sm focus:outline-none focus:ring-1 focus:ring-cyan-400"
              >
                {assignableRoles.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r] ?? r}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={createBusy}
                className="px-4 py-2 rounded-lg bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold text-sm disabled:opacity-50 transition-colors"
              >
                {createBusy ? "Creating..." : "Create"}
              </button>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 rounded-lg border border-cyan-900/50 text-white/60 hover:text-white text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
          {createError && (
            <p className="mt-3 text-sm text-red-400">{createError}</p>
          )}
        </div>
      )}

      {/* Users table */}
      <div className="bg-[#0a2d4a] rounded-xl border border-cyan-900/40 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-white/60">Loading users...</div>
        ) : error ? (
          <div className="p-8 text-center text-red-400">{error}</div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-white/60">No users found for this tenant.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[#06203b] text-white/60 text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left font-medium">Username</th>
                <th className="px-4 py-3 text-left font-medium">Role</th>
                <th className="px-4 py-3 text-left font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <UserRow
                  key={u.user_id}
                  user={u}
                  assignableRoles={assignableRoles}
                  isAdmin={isAdmin}
                  authFetch={authFetch}
                  tenantId={tenantId}
                  onRefresh={fetchUsers}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="mt-4 text-xs text-white/40">
        {isAdmin
          ? "Platform admin view — Deactivate removes platform-wide access across all tenants."
          : "Tenant admin view — actions apply to this tenant only."}
      </p>
    </div>
  );
}
