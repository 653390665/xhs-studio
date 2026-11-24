import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/*
 * 旧写稿宿主的路径要「明说没有了」，而不是被 SPA fallback 悄悄接管。
 *
 * 以前 /harness/* 由这个文件里的插件代理到 3081 上的 DeepSeek Harness。
 * 宿主已整体退场（见 docs/PLAN-FRONTEND-MERGE-v2.md），但浏览器书签、
 * 打开着的旧标签页还会来敲这个地址。SPA fallback 会返回 index.html，
 * 页面看起来"活着"，其实什么也没发生 —— 这正是本项目一直在清理的
 * 「静默降级」。这里显式返回 410。
 */
function retiredHarnessPaths(): Plugin {
  const message = [
    '写稿宿主（DeepSeek Harness）已下线。',
    '写稿请到 /write；旧页面不会回退，也不会假装还能用。',
  ].join('\n')

  const handle = (req: { url?: string }, res: { statusCode: number; setHeader: (k: string, v: string) => void; end: (b?: string) => void }, next: () => void) => {
    if (!req.url?.startsWith('/harness')) return next()
    res.statusCode = 410
    res.setHeader('Content-Type', 'text/plain; charset=utf-8')
    res.setHeader('Cache-Control', 'no-store')
    res.end(message)
  }

  return {
    name: 'retired-harness-paths',
    configureServer(server) {
      server.middlewares.use(handle)
    },
    configurePreviewServer(server) {
      server.middlewares.use(handle)
    },
  }
}

/*
 * 这个文件原来同时是「写稿宿主的启动器」：注册一个 Vite 插件，
 * 在 dev server 起来时拉起 DeepSeek Harness 子进程（3081），
 * 把 /harness/* 代理过去，并注入 205 行 CSS 去改官方的界面。
 *
 * 那条线已经整体退场：
 *   · 它的界面只能换颜色，改不了布局；
 *   · 它把写稿页从 2,726 行退化成 91 行 iframe；
 *   · 每次 dsh 升级都要复查那些构建出来的类名。
 *
 * 现在是一份普通的 Vite 配置。写稿页直连后端 /api/ai/*。
 */
export default defineConfig({
  plugins: [react(), retiredHarnessPaths()],
  server: {
    port: 5173,
    strictPort: true,
  },
})
