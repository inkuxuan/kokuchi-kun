import { defineConfig } from 'vitepress'

export default defineConfig({
  base: '/kokuchi-kun/',

  locales: {
    root: {
      label: '日本語',
      lang: 'ja',
      title: 'Kokuchi Kun',
      description: 'VRChatグループへの告知をスケジュールするDiscord Bot',
      themeConfig: {
        nav: [
          { text: 'ホーム', link: '/' },
          { text: 'はじめに', link: '/ja/getting-started' },
          { text: 'できること', link: '/ja/features' },
          { text: 'コマンド', link: '/ja/commands' },
        ],
        sidebar: [
          {
            text: 'ガイド',
            items: [
              { text: 'はじめに', link: '/ja/getting-started' },
              { text: 'できること', link: '/ja/features' },
              { text: 'リアクション一覧', link: '/ja/reactions' },
            ],
          },
          {
            text: 'リファレンス',
            items: [
              { text: 'コマンド一覧', link: '/ja/commands' },
              { text: 'よくある質問', link: '/ja/faq' },
            ],
          },
        ],
      },
    },
    en: {
      label: 'English',
      lang: 'en',
      title: 'Kokuchi Kun',
      description: 'Discord bot for scheduling VRChat group announcements',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Getting Started', link: '/en/getting-started' },
          { text: 'Features', link: '/en/features' },
          { text: 'Commands', link: '/en/commands' },
        ],
        sidebar: [
          {
            text: 'Guide',
            items: [
              { text: 'Getting Started', link: '/en/getting-started' },
              { text: 'Features', link: '/en/features' },
              { text: 'Reactions Reference', link: '/en/reactions' },
            ],
          },
          {
            text: 'Reference',
            items: [
              { text: 'Commands', link: '/en/commands' },
              { text: 'FAQ', link: '/en/faq' },
            ],
          },
        ],
      },
    },
  },

  themeConfig: {
    socialLinks: [
      { icon: 'github', link: 'https://github.com/inkuxuan/kokuchi-kun' },
    ],
  },
})
