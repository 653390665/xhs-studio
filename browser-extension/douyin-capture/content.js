// Runs on douyin.com/user/*: adds a capture button, reads the author's work
// cards, fetches each detail inside the page (the only place the request passes
// Argus), then asks the service worker to POST the list to the local backend.

(() => {
  if (window.__spiderXhsCaptureInjected) return;
  window.__spiderXhsCaptureInjected = true;

  const match = location.pathname.match(/\/user\/([^/?#]+)/);
  if (!match) return;
  const secUid = match[1];

  const COOLDOWN_MS = 10 * 60 * 1000;
  let running = false;
  let stopRequested = false;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const send = (message) =>
    new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
          } else {
            resolve(response || { ok: false, error: "no response" });
          }
        });
      } catch (error) {
        resolve({ ok: false, error: String(error) });
      }
    });

  // --- UI -------------------------------------------------------------------

  const button = document.createElement("button");
  button.id = "spider-xhs-capture-btn";
  button.type = "button";
  button.textContent = "采集这个作者";

  const panel = document.createElement("div");
  panel.id = "spider-xhs-capture-panel";
  panel.innerHTML = `
    <div class="sx-head">
      <span>采集这个作者</span>
      <button type="button" class="sx-close" aria-label="关闭">×</button>
    </div>
    <label class="sx-field">关键词（可选）
      <input id="sx-keyword" type="text" placeholder="如 AI；留空=当前可见作品" />
    </label>
    <label class="sx-field">最多条数
      <input id="sx-max" type="number" min="1" max="40" value="20" />
    </label>
    <div class="sx-hint">时长 15–75 秒由服务端再过滤；每条间隔 1.2 秒，每 10 分钟最多一次。</div>
    <div class="sx-actions">
      <button type="button" id="sx-start" class="sx-primary">开始</button>
      <button type="button" id="sx-stop" disabled>停止</button>
    </div>
    <div id="sx-progress" class="sx-progress"></div>
  `;

  document.body.appendChild(button);
  document.body.appendChild(panel);

  const keywordInput = panel.querySelector("#sx-keyword");
  const maxInput = panel.querySelector("#sx-max");
  const startButton = panel.querySelector("#sx-start");
  const stopButton = panel.querySelector("#sx-stop");
  const progress = panel.querySelector("#sx-progress");

  const setProgress = (text) => {
    progress.textContent = text;
  };

  const openPanel = () => {
    panel.classList.add("sx-open");
    button.classList.add("sx-hidden");
  };
  const closePanel = () => {
    panel.classList.remove("sx-open");
    button.classList.remove("sx-hidden");
  };

  button.addEventListener("click", openPanel);
  panel.querySelector(".sx-close").addEventListener("click", closePanel);
  stopButton.addEventListener("click", () => {
    stopRequested = true;
    setProgress("正在停止…");
  });
  startButton.addEventListener("click", () => {
    if (!running) void run();
  });

  // --- Collection -----------------------------------------------------------

  const collectIds = () => {
    const root = document.querySelector(".route-scroll-container") || document;
    const seen = new Map();
    for (const anchor of root.querySelectorAll('a[href*="/video/"]')) {
      const found = anchor.href.match(/\/video\/(\d+)/);
      if (!found) continue;
      const card = anchor.closest("li, div") || anchor;
      const text = (card.innerText || "").replace(/\s+/g, " ").trim();
      // The sidebar/recommendation cards start with 热门 and are not this
      // author's works; they were 7 of the 28 links on the profile page.
      if (text.startsWith("热门") || text.includes("抖音音乐游戏攻略")) continue;
      if (!seen.has(found[1])) seen.set(found[1], text.slice(0, 60));
    }
    return [...seen.keys()];
  };

  const searchWithin = async (keyword) => {
    const input = [...document.querySelectorAll("input")].find(
      (el) => el.placeholder === "搜索 Ta 的作品"
    );
    if (!input) return false;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    ).set;
    setter.call(input, keyword);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
      })
    );
    await sleep(3500);
    const box = document.querySelector(".route-scroll-container");
    for (let i = 0; i < 5; i++) {
      if (box) box.scrollTop = box.scrollHeight;
      await sleep(1200);
    }
    return true;
  };

  const fetchDetail = async (workId) => {
    const url =
      "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" +
      encodeURIComponent(workId) +
      "&device_platform=webapp&aid=6383&channel=channel_pc_web";
    const response = await fetch(url, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    const text = await response.text();
    let detail;
    try {
      detail = JSON.parse(text).aweme_detail;
    } catch (error) {
      return null;
    }
    if (!detail) return null;
    const video = detail.video || {};
    const play = ((video.play_addr || {}).url_list || [])[0] || "";
    if (!play) return null;
    return {
      work_id: String(detail.aweme_id || workId),
      desc: String(detail.desc || ""),
      duration: Math.round((video.duration || 0) / 1000),
      play,
      likes: (detail.statistics || {}).digg_count || 0,
      create_time: detail.create_time || 0,
      author_name: (detail.author || {}).nickname || "",
      author_sec_uid: (detail.author || {}).sec_uid || secUid,
    };
  };

  // --- Cooldown -------------------------------------------------------------

  const cooldownKey = `capture:${secUid}`;

  const readCooldown = () =>
    new Promise((resolve) => {
      chrome.storage.local.get([cooldownKey], (stored) => {
        resolve(Number(stored[cooldownKey] || 0));
      });
    });

  const writeCooldown = () =>
    new Promise((resolve) => {
      chrome.storage.local.set({ [cooldownKey]: Date.now() }, resolve);
    });

  // --- Run ------------------------------------------------------------------

  const run = async () => {
    running = true;
    stopRequested = false;
    startButton.disabled = true;
    stopButton.disabled = false;

    try {
      const last = await readCooldown();
      const wait = COOLDOWN_MS - (Date.now() - last);
      if (wait > 0) {
        setProgress(
          `这个作者 ${Math.ceil(wait / 60000)} 分钟前刚采过，先等一等（每 10 分钟一批）。`
        );
        return;
      }

      const keyword = keywordInput.value.trim();
      const max = Math.max(1, Math.min(40, Number(maxInput.value) || 20));

      if (keyword) {
        setProgress(`站内搜索「${keyword}」…`);
        const ok = await searchWithin(keyword);
        if (!ok) {
          setProgress("没找到「搜索 Ta 的作品」输入框。先在「作品」标签页再试。");
          return;
        }
      }

      let ids = collectIds();
      if (!ids.length) {
        setProgress("没有找到作品。确认在「作品」标签页，或填一个关键词。");
        return;
      }
      ids = ids.slice(0, max);
      setProgress(
        `找到 ${ids.length} 条，开始取详情（约 ${Math.ceil(ids.length * 1.2)} 秒）…`
      );

      const works = [];
      let failed = 0;
      for (let index = 0; index < ids.length; index += 1) {
        if (stopRequested) break;
        try {
          const detail = await fetchDetail(ids[index]);
          if (detail) works.push(detail);
          else failed += 1;
        } catch (error) {
          failed += 1;
        }
        setProgress(
          `取详情 ${index + 1}/${ids.length}（成功 ${works.length}，失败 ${failed}）`
        );
        if (index < ids.length - 1) await sleep(1200);
      }

      if (!works.length) {
        setProgress("全部取详情失败。刷新页面、确认登录状态后再试。");
        return;
      }

      setProgress(`发送 ${works.length} 条到本地…`);
      const result = await send({
        type: "capture",
        payload: {
          author_name: works[0].author_name || "",
          author_sec_uid: secUid,
          works,
        },
      });

      if (result && result.ok) {
        const body = result.body || {};
        await writeCooldown();
        setProgress(
          `已创建任务 #${body.job_id}：接收 ${body.accepted} 条，` +
            `已采集过 ${body.skipped_existing} 条，超时长 ${body.filtered_duration} 条。` +
            "去「素材 → 风格提取」看进度。"
        );
      } else {
        const detail =
          (result && result.body && result.body.detail) ||
          (result && result.error) ||
          "未知错误";
        setProgress(`失败：${detail}`);
      }
    } finally {
      running = false;
      startButton.disabled = false;
      stopButton.disabled = true;
    }
  };
})();
