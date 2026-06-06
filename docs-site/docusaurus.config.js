// @ts-check
// Docusaurus config for DEPT® Anatomy of Code — v2 docs site (Phase 0 scaffold).
// Brand tokens (ochre #FF4900, Syne / DM Sans / JetBrains Mono) come from
// src/css/custom.css — keep visual sympathy with the main app (CLAUDE.md).

const { themes } = require('prism-react-renderer');

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'DEPT® Anatomy of Code — Docs',
  tagline: 'Architect-grade documentation for the CODE-CODER framework and v2 platform.',
  favicon: 'img/favicon.png',

  // Deploy target (see docs/architecture/v2/08-docs-plan.md §Deployment):
  // served under https://internal.in.deptagency.com/docs/ via an Apache Alias.
  url: 'https://internal.in.deptagency.com',
  baseUrl: '/docs/',

  organizationName: 'deptagency',
  projectName: 'dept-anatomy-of-code',

  // Fail the build on a broken internal link — the sidebar and cross-refs
  // must stay sound. Markdown-link checks stay at 'warn' so an anchor typo
  // does not block a docs ship.
  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  markdown: {
    mermaid: true,
    // Docusaurus 3.10 moved the markdown-link policy under markdown.hooks.
    // Keep markdown-link checks at 'warn' so an anchor typo does not block a
    // docs ship, while internal route links stay strict via onBrokenLinks.
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  themes: [
    '@docusaurus/theme-mermaid',
    // Local search plugin (see docs/architecture/v2/08-docs-plan.md §7).
    // Docusaurus 3.5 has no official local search; this is the de-facto plugin.
    [
      // @ts-ignore — third-party type alias not bundled.
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: true,
        indexDocs: true,
        indexBlog: false,
        docsRouteBasePath: '/',
        language: ['en'],
        highlightSearchTermsOnTargetPage: true,
      },
    ],
  ],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',                    // docs are the whole site for v2.
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl: undefined,                    // No public repo edit link for v2.
          showLastUpdateTime: true,
          showLastUpdateAuthor: false,
        },
        blog: false,                             // No blog — this is a reference site.
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      image: 'img/social-card.png',
      metadata: [
        { name: 'keywords', content: 'DEPT, CODE-CODER, Adobe Experience Cloud, architecture, documentation' },
      ],
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'Anatomy of Code',
        logo: {
          alt: 'DEPT® logo',
          src: 'img/logo-dept.svg',
          srcDark: 'img/logo-dept-dark.svg',
        },
        items: [
          // Each section's landing is its intro doc. With routeBasePath '/'
          // and a doc-link category, `/section/` is not a route — the section
          // root IS `/section/intro`. Link there directly so onBrokenLinks can
          // stay 'throw'.
          { to: '/system-architecture/intro', label: 'System', position: 'left' },
          { to: '/frontend/intro', label: 'Front-end', position: 'left' },
          { to: '/content-architecture/intro', label: 'Content', position: 'left' },
          { to: '/database/intro', label: 'Database', position: 'left' },
          { to: '/quiz-management/intro', label: 'Quiz', position: 'left' },
          { to: '/deployment/intro', label: 'Deployment', position: 'left' },
        ],
      },
      footer: {
        style: 'light',
        copyright: 'DEPT® Anatomy of Code — internal documentation. © DEPT® Agency.',
      },
      prism: {
        theme: themes.github,
        darkTheme: themes.dracula,
        additionalLanguages: ['bash', 'python', 'nginx', 'apacheconf', 'json', 'sql', 'yaml'],
      },
      mermaid: {
        theme: { light: 'neutral', dark: 'dark' },
      },
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 4,
      },
    }),
};

module.exports = config;
