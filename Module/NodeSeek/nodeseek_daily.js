/* NodeSeek automatic check-in for Surge. Credentials stay in Surge local storage. */
const KEY = { cookie: "NODESEEK_COOKIE", ua: "NODESEEK_UA", version: "NODESEEK_REFRACT_VERSION" };
const HOME = "https://www.nodeseek.com";
const DEFAULT_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Mobile/15E148 Safari/604.1";
const DEFAULT_VERSION = "0.3.34";

const read = (key, fallback = "") => $persistentStore.read(key) || fallback;
const write = (value, key) => $persistentStore.write(String(value), key);
const notify = (subtitle, body = "") => $notification.post("NodeSeek 自动签到", subtitle, body);
const header = (headers, name) => {
  if (!headers) return "";
  const key = Object.keys(headers).find(k => k.toLowerCase() === name.toLowerCase());
  return key ? String(headers[key]) : "";
};
const get = options => new Promise(resolve => $httpClient.get(options, (error, response, data) => resolve({ error, response, data })));
const post = options => new Promise(resolve => $httpClient.post(options, (error, response, data) => resolve({ error, response, data })));

if (typeof $request !== "undefined") {
  const cookie = header($request.headers, "cookie");
  const ua = header($request.headers, "user-agent");
  const urlVersion = String($request.url || "").match(/\/sw\.js\?v=([0-9.]+)/);
  const version = header($request.headers, "refract-version") || (urlVersion ? urlVersion[1] : "");
  const oldCookie = read(KEY.cookie);
  if (cookie && cookie !== oldCookie) write(cookie, KEY.cookie);
  if (ua) write(ua, KEY.ua);
  if (version) write(version, KEY.version);
  if (cookie && cookie !== oldCookie) notify("Cookie 获取成功", "已保存在 Surge 本机，可等待定时签到。");
  $done({});
} else {
  run().catch(error => { notify("运行失败", String(error)); $done(); });
}

async function run() {
  const cookie = read(KEY.cookie);
  const ua = read(KEY.ua, DEFAULT_UA);
  const version = read(KEY.version, DEFAULT_VERSION);
  if (!cookie) { notify("尚未获取 Cookie", "请用 Safari 登录 NodeSeek 并进入个人主页。"); return $done(); }

  const ping = await get({
    url: HOME + "/edge-cgi/ping", timeout: 30,
    headers: { Accept: "*/*", Cookie: cookie, Referer: HOME + "/sw.js?v=" + version, "User-Agent": ua, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty" }
  });
  if (ping.error) { notify("刷新签名失败", String(ping.error)); return $done(); }
  const refractKey = header(ping.response && ping.response.headers, "refract-key-update");
  if (!refractKey) { notify("刷新签名失败", "未取得 refract-key，请重新通过验证并获取 Cookie。"); return $done(); }

  const signType = (typeof $argument !== "undefined" ? String($argument) : "random").trim().toLowerCase();
  const isRandom = signType !== "fixed" && signType !== "false" && signType !== "5";
  const modeName = isRandom ? "试试手气" : "固定鸡腿×5";
  const url = HOME + "/api/attendance?random=" + (isRandom ? "true" : "false");
  const sign = sha1(["POST", url, ua, "", refractKey].join("\n\n"));
  const result = await post({
    url, timeout: 30, body: "",
    headers: { Accept: "*/*", "Content-Type": "text/plain;charset=UTF-8", Cookie: cookie, Origin: HOME, Referer: HOME + "/", "User-Agent": ua, "refract-version": version, "refract-key": refractKey, "refract-sign": sign, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty" }
  });
  if (result.error) { notify("签到请求失败", String(result.error)); return $done(); }
  const status = Number((result.response && (result.response.status || result.response.statusCode)) || 0);
  let payload = {};
  try { payload = JSON.parse(result.data || "{}"); } catch (_) {}
  const message = payload.message || String(result.data || "").slice(0, 160) || "无返回内容";
  if (status >= 200 && status < 300 && (payload.success || /鸡腿|已完成签到|签到/.test(message))) notify("签到成功 · " + modeName, message);
  else if (status === 403) notify("签到失败：403", "Cookie、UA 或 Cloudflare 验证已失效，请重新登录获取。");
  else notify("签到异常 HTTP " + status, message);
  $done();
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
