// @ts-check
// Sidebar layout for the v2 docs site.
// Six top-level categories — one per audit section. Phase 5a fills each.

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'intro',
    {
      type: 'category',
      label: 'Front-end',
      link: { type: 'doc', id: 'frontend/intro' },
      collapsed: false,
      items: [
        'frontend/intro',
        // Phase 5a:
        //   'frontend/architecture',
        //   'frontend/module-layout',
        //   'frontend/blocks-and-registry',
        //   'frontend/router-and-modes',
        //   'frontend/theming-and-brand',
        //   'frontend/api-client',
        //   'frontend/testing-parity',
      ],
    },
    {
      type: 'category',
      label: 'Content architecture',
      link: { type: 'doc', id: 'content-architecture/intro' },
      collapsed: true,
      items: [
        'content-architecture/intro',
        // Phase 5a:
        //   'content-architecture/source-of-truth',
        //   'content-architecture/schemas',
        //   'content-architecture/seed-and-export',
        //   'content-architecture/frozen-monolith',
        //   'content-architecture/resources',
        //   'content-architecture/voice-and-layer-pattern',
      ],
    },
    {
      type: 'category',
      label: 'Database',
      link: { type: 'doc', id: 'database/intro' },
      collapsed: true,
      items: [
        'database/intro',
        // Phase 5a:
        //   'database/schema-overview',
        //   'database/er-diagram',
        //   'database/alembic-and-migrations',
        //   'database/postgres-only-features',
        //   'database/media-large-objects',
        //   'database/backup-and-restore',
      ],
    },
    {
      type: 'category',
      label: 'Deployment',
      link: { type: 'doc', id: 'deployment/intro' },
      collapsed: true,
      items: [
        'deployment/intro',
        // Phase 5a:
        //   'deployment/prerequisites',
        //   'deployment/deploy-sh-walkthrough',
        //   'deployment/apache-vhost',
        //   'deployment/systemd-and-uvicorn',
        //   'deployment/env-and-secrets',
        //   'deployment/upgrade-and-rollback',
      ],
    },
    {
      type: 'category',
      label: 'Quiz management',
      link: { type: 'doc', id: 'quiz-management/intro' },
      collapsed: true,
      items: [
        'quiz-management/intro',
        // Phase 5a:
        //   'quiz-management/question-bank',
        //   'quiz-management/quiz-lifecycle',
        //   'quiz-management/certificates',
        //   'quiz-management/dev-mode-vs-real',
        //   'quiz-management/verification',
        //   'quiz-management/admin-flows',
      ],
    },
    {
      type: 'category',
      label: 'System architecture',
      link: { type: 'doc', id: 'system-architecture/intro' },
      collapsed: true,
      items: [
        'system-architecture/intro',
        // Phase 5a:
        //   'system-architecture/modular-monolith',
        //   'system-architecture/directus-topology',
        //   'system-architecture/auth-planes',
        //   'system-architecture/caching-and-performance',
        //   'system-architecture/security-baseline',
        //   'system-architecture/observability',
      ],
    },
  ],
};

module.exports = sidebars;
