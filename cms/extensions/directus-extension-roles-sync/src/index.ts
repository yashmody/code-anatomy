import { defineHook } from '@directus/extensions-sdk';

// The four Directus staff roles whose membership is mirrored into FastAPI's
// `user_roles` (04 §7.2). Matched by NAME — must equal the role names created
// in cms/register-collections.mjs. `learner` / `feed_contributor` are
// learner-plane (app-owned) and are never sent here.
const STAFF = new Set(['content_author', 'quiz_admin', 'feed_moderator', 'platform_admin']);

const DEFAULT_URL = 'http://127.0.0.1:8000/api/cms/roles-sync';

export default defineHook(({ action, filter }, { services, getSchema, env, logger }) => {
	const { UsersService } = services as any;
	const url: string = env.FASTAPI_ROLES_SYNC_URL || DEFAULT_URL;

	// key -> email, captured in the users.delete FILTER (before the row is gone)
	// so the users.delete ACTION can still tell FastAPI which user to revoke.
	const deletingEmails = new Map<string | number, string>();

	async function usersService() {
		const schema = await getSchema();
		// accountability: null => admin read, not RBAC-scoped to the editor who
		// triggered the change (e.g. a staff user editing their own profile).
		return new UsersService({ schema, accountability: null });
	}

	async function post(email: string, role: string | null) {
		if (!email) return;
		try {
			const res = await fetch(url, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email, role }),
				signal: AbortSignal.timeout(2000),
			});
			if (!res.ok) {
				logger.warn(`[roles-sync] ${email} -> ${role}: FastAPI ${res.status}`);
			}
		} catch (err: any) {
			// Fire-and-forget: a missed sync self-heals on the next user edit, and
			// FastAPI is idempotent. Never let this block or crash the Directus write.
			logger.warn(`[roles-sync] POST failed for ${email}: ${err?.message ?? err}`);
		}
	}

	// Re-read the user's CURRENT role + status (never trust meta.payload, which on
	// update carries only the changed fields) and reconcile. Idempotent.
	async function reconcile(keys: Array<string | number>) {
		if (!keys.length) return;
		const svc = await usersService();
		const rows = await svc.readMany(keys, { fields: ['email', 'role.name', 'status'] });
		for (const u of rows as any[]) {
			const roleName: string | null = u?.role?.name ?? null;
			const active = u?.status === 'active';
			const role = active && roleName && STAFF.has(roleName) ? roleName : null;
			await post(u?.email, role);
		}
	}

	// New staff user (create fires once per item -> meta.key is a single key).
	action('users.create', (meta: any) => {
		void reconcile([meta.key]).catch((e) => logger.warn(`[roles-sync] create: ${e}`));
	});

	// Role assignment or (de)activation. Skip the high-frequency self-edits
	// (last_access, theme, language, last_page) that touch neither role nor status.
	action('users.update', (meta: any) => {
		const payload = meta?.payload ?? {};
		if (!('role' in payload) && !('status' in payload)) return;
		void reconcile(meta.keys ?? []).catch((e) => logger.warn(`[roles-sync] update: ${e}`));
	});

	// Hard delete: capture key -> email BEFORE deletion (filter runs first)...
	filter('users.delete', async (payload: any) => {
		const keys: Array<string | number> = Array.isArray(payload) ? payload : [];
		if (keys.length) {
			try {
				const svc = await usersService();
				const rows = await svc.readMany(keys, { fields: ['email'] });
				for (const u of rows as any[]) {
					if (u?.id != null && u?.email) deletingEmails.set(u.id, u.email);
				}
			} catch (e) {
				logger.warn(`[roles-sync] delete capture failed: ${e}`);
			}
		}
		return payload; // unchanged — we only observe
	});

	// ...then revoke their staff roles once the delete has committed.
	action('users.delete', (meta: any) => {
		const keys: Array<string | number> = Array.isArray(meta?.payload) ? meta.payload : [];
		for (const key of keys) {
			const email = deletingEmails.get(key);
			deletingEmails.delete(key);
			if (email) void post(email, null);
		}
	});
});
