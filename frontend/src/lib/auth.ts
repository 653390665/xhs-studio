/**
 * auth.ts — token 存取（localStorage）+ 当前用户
 *
 * 后端契约（实测）：
 * POST /api/auth/login {username,password}
 *   → { access_token, refresh_token, token_type:"bearer", user:{id,username} }
 * 401 时统一由 api.ts 清 token 并跳登录。
 */

const ACCESS_TOKEN_KEY = "xhs.access_token";
const REFRESH_TOKEN_KEY = "xhs.refresh_token";
const USER_KEY = "xhs.user";
const REMEMBER_KEY = "xhs.remember_username";

/** 登录接口返回的 user 结构（实测只有 id / username） */
export interface AuthUser {
  id: number;
  username: string;
}

/** 登录接口完整响应（实测） */
export interface LoginResponse {
  access_token: string;
  refresh_token?: string;
  token_type?: string;
  user: AuthUser;
}

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // 隐私模式/被禁用时 localStorage 会抛异常，不能因此白屏
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* 存不进去就退化为仅当前会话可用，不阻断流程 */
  }
}

function safeRemove(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export function getToken(): string | null {
  return safeGet(ACCESS_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  const token = getToken();
  return typeof token === "string" && token.length > 0;
}

export function setSession(payload: LoginResponse): void {
  safeSet(ACCESS_TOKEN_KEY, payload.access_token);
  if (payload.refresh_token) {
    safeSet(REFRESH_TOKEN_KEY, payload.refresh_token);
  }
  if (payload.user) {
    safeSet(USER_KEY, JSON.stringify(payload.user));
  }
}

export function clearSession(): void {
  safeRemove(ACCESS_TOKEN_KEY);
  safeRemove(REFRESH_TOKEN_KEY);
  safeRemove(USER_KEY);
}

export function getStoredUser(): AuthUser | null {
  const raw = safeGet(USER_KEY);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "username" in parsed &&
      typeof (parsed as { username: unknown }).username === "string"
    ) {
      const candidate = parsed as { id?: unknown; username: string };
      return {
        id: typeof candidate.id === "number" ? candidate.id : 0,
        username: candidate.username,
      };
    }
    return null;
  } catch {
    return null;
  }
}

/* ---------- 记住账号（登录页用，不存密码） ---------- */

export function getRememberedUsername(): string {
  return safeGet(REMEMBER_KEY) ?? "";
}

export function setRememberedUsername(username: string): void {
  if (username) {
    safeSet(REMEMBER_KEY, username);
  } else {
    safeRemove(REMEMBER_KEY);
  }
}

/* ---------- 401 清场：带上"为什么被踢出去"的原因，登录页可显示 ---------- */

let sessionExpiredFlag = false;

export function markSessionExpired(): void {
  sessionExpiredFlag = true;
}

export function consumeSessionExpired(): boolean {
  const value = sessionExpiredFlag;
  sessionExpiredFlag = false;
  return value;
}

const API_BASE=(import.meta.env.VITE_API_BASE||(import.meta.env.DEV?'http://127.0.0.1:8000':'')).replace(/\/+$/,'');
let renewal:Promise<boolean>|undefined;let lastRenewalAt=0;
/** 正常应用续期现有会话；不导出token，不清API设置。 */
export async function renewSession(force=false):Promise<boolean>{if(renewal)return renewal;if(!force&&Date.now()-lastRenewalAt<120000)return false;const before=getToken(),refresh=safeGet(REFRESH_TOKEN_KEY);if(!before||!refresh)return false;lastRenewalAt=Date.now();renewal=(async()=>{try{const r=await fetch(API_BASE+'/api/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:refresh}),signal:AbortSignal.timeout(8000)});if(!r.ok)return false;const raw=await r.json(),v=raw.data??raw;if(getToken()!==before||typeof v.access_token!=='string'||!/^[^\s]{10,4096}$/.test(v.access_token))return false;const user=getStoredUser();if(!user||v.user&&String(v.user.id)!==String(user.id))return false;setSession({access_token:v.access_token,refresh_token:typeof v.refresh_token==='string'?v.refresh_token:undefined,user});return true;}catch{return false;}finally{renewal=undefined;}})();return renewal;}
