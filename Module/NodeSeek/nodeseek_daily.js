/* NodeSeek automatic check-in for Surge. Credentials stay in Surge local storage. */
const KEY = { cookie: "NODESEEK_COOKIE", ua: "NODESEEK_UA", version: "NODESEEK_REFRACT_VERSION", refractKey: "NODESEEK_REFRACT_KEY" };
const HOME = "https://www.nodeseek.com";
const DEFAULT_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Mobile/15E148 Safari/604.1";
const DEFAULT_VERSION = "0.3.34";

const read = (key, fallback = "") => $persistentStore.read(key) || fallback;
const write = (value, key) => $persistentStore.write(String(value), key);
const notify = (subtitle, body = "") => $notification.post("NodeSeek 自动签到", subtitle, body);
const header = (headers, name) => {
  if (!headers) return "";
  const key = Object.keys(headers).find(k => k.toLowerCase() === name.toLowerCase());
  if (!key) return "";
  const value = headers[key];
  return Array.isArray(value) ? value.join("; ") : String(value);
};
const log = message => console.log("[NodeSeek] " + message);
const get = options => new Promise(resolve => $httpClient.get(options, (error, response, data) => resolve({ error, response, data })));
const post = options => new Promise(resolve => $httpClient.post(options, (error, response, data) => resolve({ error, response, data })));

if (typeof $request !== "undefined") {
  const cookie = header($request.headers, "cookie");
  const ua = header($request.headers, "user-agent");
  const urlVersion = String($request.url || "").match(/\/sw\.js\?v=([0-9.]+)/);
  const version = header($request.headers, "refract-version") || (urlVersion ? urlVersion[1] : "");
  const refractKey = header($request.headers, "refract-key");
  const oldCookie = read(KEY.cookie);
  if (cookie && cookie !== oldCookie) write(cookie, KEY.cookie);
  if (ua) write(ua, KEY.ua);
  if (version) write(version, KEY.version);
  if (refractKey) write(refractKey, KEY.refractKey);
  if (cookie && cookie !== oldCookie) notify("Cookie 获取成功", refractKey ? "Cookie 与 refract-key 已保存，可等待定时签到。" : "Cookie 已保存；请打开签到页以捕获 refract-key。");
  $done({});
} else {
  run().catch(error => { notify("运行失败", String(error)); $done(); });
}

async function run() {
  const cookie = read(KEY.cookie);
  const ua = read(KEY.ua, DEFAULT_UA);
  const version = read(KEY.version, DEFAULT_VERSION);
  let refractKey = read(KEY.refractKey);
  log("Cron started; mode=" + (typeof $argument !== "undefined" ? String($argument) : "random") + "; cookieLength=" + cookie.length + "; version=" + version + "; refractKey=" + (refractKey ? "stored" : "missing"));
  if (!cookie) { log("No stored Cookie"); notify("尚未获取 Cookie", "请用 Safari 登录 NodeSeek 并进入个人主页。"); return $done(); }
  if (!refractKey) { log("No stored refract-key"); notify("尚未获取 refract-key", "请用 Safari 打开 NodeSeek 签到页并刷新一次，再运行签到。"); return $done(); }

  const pingUrl = HOME + "/edge-cgi/ping";
  const pingSign = makeRefractSign(refractKey, pingUrl, "GET", ua);
  const ping = await get({
    url: pingUrl, timeout: 30,
    headers: { Accept: "*/*", Cookie: cookie, Referer: HOME + "/sw.js?v=" + version, "User-Agent": ua, "refract-version": version, "refract-key": refractKey, "refract-sign": pingSign, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty" }
  });
  if (ping.error) { log("Ping error: " + String(ping.error)); notify("刷新签名失败", String(ping.error)); return $done(); }
  const updatedKey = header(ping.response && ping.response.headers, "refract-key-update");
  const pingStatus = Number((ping.response && (ping.response.status || ping.response.statusCode)) || 0);
  if (updatedKey) { refractKey = updatedKey; write(refractKey, KEY.refractKey); }
  log("Ping HTTP " + pingStatus + "; refractKey=" + (updatedKey ? "updated" : "unchanged"));
  if (pingStatus === 401 || pingStatus === 403) { notify("刷新签名失败：" + pingStatus, "refract-key、Cookie、UA 或网络环境已失效；请在 Safari 刷新签到页后重试。"); return $done(); }
  if (pingStatus < 200 || pingStatus >= 400) { notify("刷新签名异常 HTTP " + pingStatus, String(ping.data || "").slice(0, 160)); return $done(); }

  const signType = (typeof $argument !== "undefined" ? String($argument) : "random").trim().toLowerCase();
  const isRandom = signType !== "fixed" && signType !== "false" && signType !== "5";
  const modeName = isRandom ? "试试手气" : "固定鸡腿×5";
  const url = HOME + "/api/attendance?random=" + (isRandom ? "true" : "false");
  const sign = makeRefractSign(refractKey, url, "POST", ua);
  const result = await post({
    url, timeout: 30, body: "",
    headers: { Accept: "*/*", "Content-Type": "text/plain;charset=UTF-8", Cookie: cookie, Origin: HOME, Referer: HOME + "/", "User-Agent": ua, "refract-version": version, "refract-key": refractKey, "refract-sign": sign, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty" }
  });
  if (result.error) { log("Attendance request error: " + String(result.error)); notify("签到请求失败", String(result.error)); return $done(); }
  const status = Number((result.response && (result.response.status || result.response.statusCode)) || 0);
  let payload = {};
  try { payload = JSON.parse(result.data || "{}"); } catch (_) {}
  const message = payload.message || String(result.data || "").slice(0, 160) || "无返回内容";
  log("Attendance HTTP " + status + "; response=" + message.replace(/\s+/g, " "));
  if (status >= 200 && status < 300 && (payload.success || /鸡腿|已完成签到|签到/.test(message))) notify("签到成功 · " + modeName, message);
  else if (status === 403) notify("签到失败：403", "refract-key/签名、Cookie、UA 或 Cloudflare 验证已失效；请用 Safari 刷新签到页后重试。");
  else notify("签到异常 HTTP " + status, message);
  $done();
}

function makeRefractSign(refractKey, url, method, ua) {
  return sha1(String(refractKey || "") + String(url || "") + String(method || "").toUpperCase() + String(ua || ""));
}

function sha1(message) {
  const text = unescape(encodeURIComponent(message)), words = [];
  for (let i = 0; i < text.length; i++) words[i >> 2] |= text.charCodeAt(i) << (24 - (i % 4) * 8);
  const bitLength = text.length * 8;
  words[bitLength >> 5] |= 0x80 << (24 - (bitLength % 32));
  words[((bitLength + 64 >> 9) << 4) + 15] = bitLength;
  const rotate = (value, bits) => (value << bits) | (value >>> (32 - bits));
  const hex = value => { let out = ""; for (let i = 7; i >= 0; i--) out += ((value >>> (i * 4)) & 15).toString(16); return out; };
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Array(80);
  for (let offset = 0; offset < words.length; offset += 16) {
    for (let i = 0; i < 16; i++) w[i] = words[offset + i] | 0;
    for (let i = 16; i < 80; i++) w[i] = rotate(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i++) {
      let f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const temp = (rotate(a, 5) + f + e + k + w[i]) | 0;
      e = d; d = c; c = rotate(b, 30) | 0; b = a; a = temp;
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0; h4 = (h4 + e) | 0;
  }
  return hex(h0) + hex(h1) + hex(h2) + hex(h3) + hex(h4);
}
