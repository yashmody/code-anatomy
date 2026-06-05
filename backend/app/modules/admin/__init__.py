"""Admin module — platform-admin-only role assignment REST (04 §7.2).

Surfaces the deferred Q-3 admin-roles API: grant/revoke/list capability roles
for learner-plane users (the `learner → feed_contributor` path, plus the full
taxonomy under a platform_admin). All writes go through `core.users`, which is
the single audited writer of `user_roles`.
"""
