// @ts-check
// Docusaurus config for DEPT® Anatomy of Code — v2 docs site (Phase 0 scaffold).
// Brand tokens (ochre #FF4900, Syne / DM Sans / JetBrains Mono) come from
// src/css/custom.css — keep visual sympathy with the main app (CLAUDE.md).

const { themes } = require('prism-react-renderer');

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'DEPT® Anatomy of Code — Docs',
  tagline: 'Architect-grade documentation for the CODE-CODER framework and v2 platform.',
  favicon: 'img/favicon.ico',

  // Placeholders — Phase 5a sets these to the real deploy target.
  // Default recommendation (see docs/architecture/v2/08-docs-plan.md §Deployment):
  // serve under https://internal.in.deptagency.com/docs/ via an Apache Alias.
  url: 'https://internal.in.deptagency.com',
  baseUrl: '/docs/',

  organizationName: 'deptagency',
  projectName: 'dept-anatomy-of-code',

  onBrokenLinks: 'warn',          // Phase 5a CI flips this to 'throw'.
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  markdown: {
    mermaid: true,
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
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'Anatomy of Code',
        logo: {
          alt: 'DEPT logo',
          src: 'img/logo-dept.svg',
          srcDark: 'img/logo-dept.svg',
        },
        items: [
          { to: '/frontend/', label: 'Front-end', position: 'left' },
          { to: '/content-architecture/', label: 'Content', position: 'left' },
          { to: '/database/', label: 'Database', position: 'left' },
          { to: '/deployment/', label: 'Deployment', position: 'left' },
          { to: '/quiz-management/', label: 'Quiz', position: 'left' },
          { to: '/system-architecture/', label: 'System', position: 'left' },
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
