/**
 * 打包版前端必须用「同源」地址
 *
 * 这条是踩出来的，写在这里免得下次又改回去。
 *
 * 旧写法：`API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000"`
 *
 * 开发时没问题——Vite 在 5173、后端在 8000，跨端口只能写绝对地址。
 *
 * 打包版会坏：
 *   1. 安装器启动时端口是 `pick_port("127.0.0.1", 8000)` 选的。8000 被别的
 *      程序占用就换 8001、8002……而写死的 8000 会让每个请求都打到别人身上，
 *      或者根本连不上。错误看起来像「后端挂了」，其实后端好好跑在 8001。
 *   2. 前端由后端同源提供（`FRONTEND_SERVE_STATIC=true` + StaticFiles），
 *      本来就该用相对路径，写绝对地址等于自己给自己制造一个跨域问题。
 *
 * 所以现在的规则：
 *   开发（`import.meta.env.DEV`）→ `http://127.0.0.1:8000`
 *   构建产物                     → 空串，即同源
 *   显式给了 `VITE_API_BASE`     → 听它的（有人要前后端分离部署时用）
 */

/*
 * 单独一个文件而不是塞进 api.ts：`api.ts` 已经 import 了 `auth.ts`（token 存取），
 * 如果 auth 反过来 import api 就是循环依赖，模块初始化顺序一变就会拿到
 * undefined，症状是「登录接口地址是 undefined」。
 *
 * 这里谁都不依赖，两边都可以安全 import。
 */

const configured = (import.meta.env.VITE_API_BASE ?? "").trim();

export const API_BASE: string = configured
  ? configured.replace(/\/+$/, "")
  : import.meta.env.DEV
    ? "http://127.0.0.1:8000"
    : "";

/** 人读的后端地址，用于「运行状态」页显示 */
export function apiBaseLabel(): string {
  return API_BASE || "同源（由后端直接提供页面）";
}
