/**
 * silentLogin.ts — 免账号密码进站
 *
 * 目的：演示阶段不再让使用者填账号密码。
 *
 * 做法不是"假装登录"：仍然真实调用 POST /api/auth/login 换取 token，
 * 只是把凭据固定在本机，登录这一步由页面自动完成，用户看不到表单。
 *
 * 为什么不能直接把 token 写死：
 *   token 有 ~30 天有效期，写死会在某天静默失效，且无法刷新。
 *   每次启动现换一个，才和正常登录一样可靠。
 *
 * 为什么凭据放在前端代码里可以接受：
 *   这是本机演示库，后端只监听 127.0.0.1，没有外部可访问面。
 *   将来要给别人用，应改成后端免鉴权或环境变量注入。
 */

import { post, get, ApiError } from "./api";
import { setSession, isAuthenticated, getToken, clearSession, type LoginResponse } from "./auth";

/** 演示账号。要和后端库里实际的用户一致。 */
const DEMO_USERNAME = "demo";
const DEMO_PASSWORD = "Demo123456";

/**
 * 防止并发重复登录：
 * 多个页面同时挂载时只会真正发一次请求，其余等同一个 Promise。
 */
let inflight: Promise<boolean> | null = null;

/** 上一次失败的原因，供界面显示真实错误，而不是笼统的"登录失败" */
let lastError: string | null = null;

export function getSilentLoginError(): string | null {
  return lastError;
}

/** 已经登录过就不用再换 token */
export function hasSession(): boolean {
  return isAuthenticated();
}

/**
 * 探测本地 token 是否还能用。
 *
 * 为什么需要这一步：
 *   这个后端的鉴权有个坑——token 无效时它不返回 401，而是 500 直接崩，
 *   而且 500 响应没有 CORS 头，浏览器会当成网络失败（net::ERR_FAILED）。
 *   前端因此既看不到 401、也读不到错误体，"401 自动重登"这条常规链路根本走不到，
 *   最后表现成一堆空列表，特别难排查。
 *
 *   所以这里用 /api/auth/me 当探针：200 才算 token 有效，
 *   无效就直接换新 token，不让坏 token 进入业务请求。
 */
async function probeToken(): Promise<boolean> {
  const token = getToken();
  if (!token) return false;
  try {
    await get("/api/auth/me", { skipAuthRedirect: true });
    return true;
  } catch {
    return false;
  }
}

/**
 * 确保有可用会话。
 * @returns true 表示已拿到 token，可以继续请求接口
 */
export async function ensureSession(): Promise<boolean> {
  if (inflight) return inflight;

  /*
   * 整段（探测 + 换 token）必须同属一个 inflight。
   *
   * 之前的写法把 probeToken 放在 inflight 外面，而它是 await 的：
   * 两个组件同时进站会在 await 处一起越过判断，各发一次登录请求。
   * 现在从探测开始就纳入同一个 Promise，只跑一次。
   */
  inflight = (async () => {
    try {
      // 本地有 token 也要先验：坏 token 会在业务请求上炸成 500 + CORS 失败
      if (isAuthenticated() && (await probeToken())) return true;
      if (isAuthenticated()) clearSession();

      const res = await post<LoginResponse>(
        "/api/auth/login",
        { username: DEMO_USERNAME, password: DEMO_PASSWORD },
        // 这里是"登录"这个动作本身，401 不应该触发"会话过期跳登录"的逻辑
        { skipAuthRedirect: true },
      ).catch(async (loginError: unknown) => {
        /*
         * 库里还没有这个账号 —— 说明是全新装的一份（朋友第一次跑）。
         *
         * 不能直接报"进不去"：后端允许注册（POST /api/auth/register，
         * 只要用户名 + 密码），而全新的 data 目录里本来就没有 demo 账号。
         * 所以先注册、再登录一次。注册也可能失败（账号已存在但密码不对），
         * 那就把注册的原错误抛出去，不掩盖真正的认证问题。
         */
        const status = loginError instanceof ApiError ? loginError.status : 0;
        if (status !== 401 && status !== 400) throw loginError;
        await post(
          "/api/auth/register",
          { username: DEMO_USERNAME, password: DEMO_PASSWORD },
          { skipAuthRedirect: true },
        );
        return post<LoginResponse>(
          "/api/auth/login",
          { username: DEMO_USERNAME, password: DEMO_PASSWORD },
          { skipAuthRedirect: true },
        );
      });
      setSession(res);
      lastError = null;
      return true;
    } catch (err) {
      // 不吞错：把后端真实返回记下来，界面要能显示出来
      if (err instanceof ApiError) {
        lastError = err.message;
      } else if (err instanceof Error) {
        lastError = err.message;
      } else {
        lastError = "未知错误";
      }
      return false;
    } finally {
      inflight = null;
    }
  })();

  return inflight;
}
