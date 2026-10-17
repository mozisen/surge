/*
 * po0 防火墙自动加白
 *
 * 兼容：
 * Surge / Stash / Shadowrocket / Loon / Quantumult X
 *
 * 功能：
 * POST /api/firewall/<token>/add
 * 将访问 po0 API 时服务端检测到的当前出口 IP 加入白名单。
 *
 * 服务端返回示例：
 * {
 *   enabled,
 *   whitelist: [{ ip, slot }],
 *   limit,
 *   currentIp
 * }
 *
 * 注意：
 * currentIp 代表访问 po0 API 时使用的出口，
 * 并不保证等同于访问其他目标服务器时的出口 IP。
 *
 * 加白粒度：
 * IPv4 /24（C 段）
 *
 * token 来源优先级：
 * 1. 模块参数 argument：tokens=pgnfw_xxx,pgnfw_yyy
 * 2. 持久化存储：po0fw_tokens
 * 3. INLINE_TOKENS
 *
 * 固定槽位：
 * pgnfw_xxx@0
 *
 * 优化：
 * - network-changed 后延迟 1.5 秒，等待网络路由稳定
 * - Surge 下 HTTP 请求显式 DIRECT
 * - HTTP 非 2xx 返回明确错误
 * - token 自动去重
 * - 同 token 多槽位冲突预检
 * - @slot 严格数字校验
 * - 持久化状态按 token hash 保存，不受 token 排列顺序影响
 * - 蜂窝 📶 标记兼容精确 IP 与 /24
 * - Surge 指定代理 HTTP HEAD 连通性测试，失败后限次重新加白
 * - 结构化运行日志（时间、触发来源、每轮 API/代理检测/重试）
 * - 日志级别和最近 20 次运行摘要（不会保存 token）
 */


/* =========================================================
 * 配置
 * ======================================================= */

var INLINE_TOKENS = "";

var API_BASE = "https://124.221.69.228/api/firewall/";

var STORE_PREFIX = "po0_fw_";
var TOKENS_KEY = "po0fw_tokens";

var HIST_WINDOW_MS = 24 * 3600 * 1000;

// HTTP 重试
var HTTP_RETRY = 3;
var HTTP_RETRY_DELAY_MS = 1500;

// network-changed 后等待网络稳定
var NETWORK_CHANGED_DELAY_MS = 1500;

// Surge 原生代理连通性测试，默认采用 HTTP 204 检测地址。
var DEFAULT_PROXY_TEST_URL = "http://cp.cloudflare.com/generate_204";
var PROXY_RETRY_DELAY_MS = 1800;
var MAX_PROXY_RETRIES = 5;

// 运行日志：detail 全流程，summary 仅概要/警告，off 关闭控制台日志。
var LOG_LEVEL = "summary";
var RUN_ID = Date.now().toString(36);
var RUN_STARTED_AT = Date.now();
var RUN_TRIGGER = "unknown";
var RUN_HISTORY_KEY = STORE_PREFIX + "run_history";
var MAX_RUN_HISTORY = 20;


/* =========================================================
 * 环境检测
 * ======================================================= */

var isQX = typeof $task !== "undefined";
var isSurgeLike = typeof $httpClient !== "undefined";

var envInfo = "";

try {
  if (
    typeof $environment !== "undefined" &&
    $environment
  ) {
    envInfo = JSON.stringify($environment).toLowerCase();
  }
} catch (e) {}


var isLoon =
  typeof $loon !== "undefined" ||
  envInfo.indexOf("loon") >= 0;


var isSurge =
  envInfo.indexOf("surge-version") >= 0;


var isShadowrocket =
  envInfo.indexOf("shadowrocket") >= 0;


var isStash =
  envInfo.indexOf("stash") >= 0;


var isSurgeFamily =
  isSurge ||
  isShadowrocket ||
  isStash;


/*
 * HTTP timeout：
 *
 * Surge / Shadowrocket / Stash：
 * 秒
 *
 * Loon / Quantumult X：
 * 毫秒
 *
 * 无法判断客户端时不主动设置 HTTP timeout，
 * 使用客户端自己的默认值。
 *
 * 模块里的 timeout=60 只控制整个脚本最大执行时间，
 * 与单次 HTTP 请求 timeout 不是同一个概念。
 */

var REQUEST_TIMEOUT = null;

if (isLoon || isQX) {
  REQUEST_TIMEOUT = 15000;
} else if (isSurgeFamily) {
  REQUEST_TIMEOUT = 15;
}



/* =========================================================
 * 结构化日志与运行摘要历史
 * - 使用控制台输出运行轨迹；日志时间戳为 UTC ISO 8601。
 * - 不输出完整 token 或 API 地址中的 token。
 * - 运行摘要保存在 $persistentStore，最多保留最近 20 次。
 * ======================================================= */
function redactSensitive(value) {
  var text = String(value === undefined || value === null ? "" : value);
  return text
    .replace(/\/api\/firewall\/[^/?\s"'<>]+/gi, "/api/firewall/[REDACTED]")
    .replace(/pgnfw_[A-Za-z0-9_-]+/g, "pgnfw_[REDACTED]")
    .slice(0, 320);
}

function safeTestUrl(url) {
  return String(url || "")
    .replace(/\/\/[^/@\s]+@/, "//[AUTH]@")
    .split("?")[0]
    .split("#")[0]
    .slice(0, 180);
}

function logEvent(level, phase, message) {
  if (LOG_LEVEL === "off" || (LOG_LEVEL !== "debug" && level !== "BRIEF")) return;
  try {
    if (typeof console === "undefined" || typeof console.log !== "function") return;
    // Surge 已显示时间、会话 ID，避免重复打印。
    console.log("[po0] " + redactSensitive(
      level === "BRIEF" ? message : "[" + phase + "] " + message
    ));
  } catch (e) {}
}

function writeLogbookSummary(message) {
  try {
    if (typeof $surge !== "undefined" && $surge &&
        typeof $surge.logbook === "function") {
      $surge.logbook("[po0fw] " + redactSensitive(message));
    }
  } catch (e) {
    logEvent("WARN", "日志簿", "写入 Surge Logbook 失败：" +
      redactSensitive(e && e.message ? e.message : e));
  }
}

function saveRunSummary(record) {
  try {
    var records = JSON.parse(storeRead(RUN_HISTORY_KEY) || "[]");
    if (!Array.isArray(records)) records = [];
    records.push(record);
    if (records.length > MAX_RUN_HISTORY) {
      records = records.slice(-MAX_RUN_HISTORY);
    }
    var stored = storeWrite(JSON.stringify(records), RUN_HISTORY_KEY);
    if (stored === false) {
      logEvent("WARN", "存储", "最近运行摘要保存失败，当前环境可能不支持持久化存储");
    } else {
      logEvent("DETAIL", "存储", "已保存最近运行摘要，当前 " + records.length + "/" + MAX_RUN_HISTORY + " 条");
    }
  } catch (e) {
    logEvent("WARN", "存储", "最近运行摘要保存异常：" + redactSensitive(e && e.message ? e.message : e));
  }
}


/* =========================================================
 * 基础工具
 * ======================================================= */

function storeRead(key) {

  if (isQX) {
    return $prefs.valueForKey(key);
  }

  if (
    typeof $persistentStore !== "undefined"
  ) {
    return $persistentStore.read(key);
  }

  return null;
}


function storeWrite(value, key) {

  if (isQX) {
    return $prefs.setValueForKey(value, key);
  }

  if (
    typeof $persistentStore !== "undefined"
  ) {
    return $persistentStore.write(value, key);
  }

  return false;
}


function notify(title, subtitle, body) {

  if (isQX) {

    $notify(
      title,
      subtitle,
      body
    );

  } else if (
    typeof $notification !== "undefined"
  ) {

    $notification.post(
      title,
      subtitle,
      body
    );
  }
}


function finish(title, content, allOk) {

  if (isQX) {
    $done();
    return;
  }

  $done({
    title: title,
    content: content,

    icon:
      allOk
        ? "checkmark.shield"
        : "exclamationmark.shield",

    "icon-color":
      allOk
        ? "#34C759"
        : "#FF3B30"
  });
}


function delay(ms) {

  return new Promise(function (resolve) {

    if (
      ms > 0 &&
      typeof setTimeout === "function"
    ) {

      setTimeout(
        resolve,
        ms
      );

    } else {

      resolve();
    }
  });
}


/* =========================================================
 * 当前触发事件
 * ======================================================= */

function getEventName() {

  try {

    if (
      typeof $event === "undefined" ||
      !$event
    ) {
      return "";
    }

    if (
      typeof $event === "string"
    ) {
      return $event;
    }

    if (
      typeof $event === "object"
    ) {

      return String(
        $event.name ||
        $event.eventName ||
        ""
      );
    }

  } catch (e) {}

  return "";
}


/* =========================================================
 * 稳定 Hash
 *
 * 用 token hash 作为存储 ID，
 * 避免 token 调换顺序后历史记录串号。
 * ======================================================= */

function hashString(str) {

  var hash = 2166136261;

  for (
    var i = 0;
    i < str.length;
    i++
  ) {

    hash ^= str.charCodeAt(i);

    if (
      typeof Math.imul === "function"
    ) {

      hash =
        Math.imul(
          hash,
          16777619
        );

    } else {

      hash =
        (
          hash *
          16777619
        ) >>> 0;
    }
  }

  return (
    hash >>> 0
  ).toString(16);
}


/* =========================================================
 * HTTP 错误描述
 * ======================================================= */

function describeHttpError(error) {

  var text = "";

  if (
    error === null ||
    error === undefined
  ) {

    text = "";

  } else if (
    typeof error === "object"
  ) {

    text = String(
      error.message ||
      error.error ||
      error.description ||
      ""
    );

  } else {

    text = String(error);
  }


  text = text.replace(
    /^\s+|\s+$/g,
    ""
  );


  if (
    text === "" ||
    text === "null" ||
    text === "undefined" ||
    text === "{}"
  ) {

    return (
      "网络请求失败" +
      "（超时 / TLS 握手失败 / 被拦截）"
    );
  }

  return text;
}


/* =========================================================
 * HTTP 请求
 * ======================================================= */

function httpRequestOnce(
  method,
  opts
) {

  return new Promise(
    function (resolve) {

      /* Quantumult X */

      if (isQX) {

        opts.method = method;

        $task.fetch(opts).then(

          function (resp) {

            resolve({
              body: resp.body,
              status:
                resp.statusCode ||
                resp.status
            });
          },

          function (err) {

            resolve({
              error:
                describeHttpError(
                  (
                    err &&
                    err.error
                  ) ||
                  err
                )
            });
          }
        );

        return;
      }


      /* Surge / Loon / Stash / Shadowrocket */

      if (isSurgeLike) {

        var cb =
          function (
            error,
            response,
            body
          ) {

            if (error) {

              resolve({
                error:
                  describeHttpError(
                    error
                  )
              });

            } else {

              resolve({

                body: body,

                status:
                  response &&
                  (
                    response.status ||
                    response.statusCode
                  )
              });
            }
          };


        /*
         * Shadowrocket 的 $httpClient
         * 是 ObjC 桥接对象，
         * 不能把 post/get 解引用后调用。
         */

        if (
          method === "POST"
        ) {

          $httpClient.post(
            opts,
            cb
          );

        } else if (method === "HEAD") {

          $httpClient.head(opts, cb);

        } else {

          $httpClient.get(
            opts,
            cb
          );
        }

        return;
      }


      resolve({
        error:
          "unsupported client"
      });
    }
  );
}


/* =========================================================
 * 是否属于可重试服务端错误
 * ======================================================= */

function isRetryableServerError(r) {

  if (
    !r ||
    !r.status
  ) {
    return false;
  }


  /* 5xx */

  if (
    r.status >= 500
  ) {
    return true;
  }


  /* 成功 */

  if (
    r.status >= 200 &&
    r.status < 300
  ) {
    return false;
  }


  /*
   * 403 通常是固定槽位冲突，
   * 重试没有意义。
   */

  if (
    r.status === 403
  ) {
    return false;
  }


  /*
   * JSON 错误通常表示确定性错误：
   * token 错误、参数错误等。
   */

  try {

    JSON.parse(
      r.body
    );

    return false;

  } catch (e) {

    /*
     * 非 JSON body，例如：
     *
     * Error
     *
     * 有可能是服务端瞬时异常。
     */

    return true;
  }
}


/* =========================================================
 * 带重试 HTTP
 * ======================================================= */

function httpRequest(
  method,
  opts,
  attempt,
  logTag
) {

  attempt =
    attempt ||
    1;

  var httpStartedAt = Date.now();
  var tag = logTag || "po0 API";
  logEvent("DETAIL", "API/HTTP", tag + " 底层 POST 尝试 " + attempt + "/" + HTTP_RETRY +
    " policy=" + (isSurge ? "DIRECT" : "由客户端路由决定") +
    " timeout=" + (REQUEST_TIMEOUT === null ? "默认" : REQUEST_TIMEOUT));

  return httpRequestOnce(
    method,
    opts
  ).then(
    function (r) {

      var spent = Date.now() - httpStartedAt;
      logEvent(r.error ? "WARN" : "DETAIL", "API/HTTP", tag + " 底层尝试 " + attempt +
        " 结果 HTTP=" + (r.status || "-") + " duration=" + spent + "ms" +
        (r.error ? " error=" + r.error : ""));

      if (
        !r.error &&
        !isRetryableServerError(r)
      ) {

        return r;
      }


      if (
        attempt >=
        HTTP_RETRY
      ) {

        if (r.error) {

          r.error =
            r.error +
            "（已重试 " +
            HTTP_RETRY +
            " 次）";
        }

        return r;
      }


      logEvent("WARN", "API/重试", tag + " 传输异常或可重试响应；等待 " +
        (HTTP_RETRY_DELAY_MS * attempt) + "ms 重试底层请求");
      return delay(
        HTTP_RETRY_DELAY_MS *
        attempt
      ).then(
        function () {

          return httpRequest(
            method,
            opts,
            attempt + 1,
            tag
          );
        }
      );
    }
  );
}


/* =========================================================
 * 获取模块参数
 * ======================================================= */

function getArgumentTokens() {

  if (
    typeof $argument === "undefined" ||
    $argument === null
  ) {
    return "";
  }


  /*
   * Loon：
   * argument 可能是对象
   */

  if (
    typeof $argument === "object"
  ) {

    return String(
      $argument.tokens ||
      ""
    );
  }


  if (
    typeof $argument !== "string" ||
    $argument.length === 0
  ) {

    return "";
  }


  var arg = $argument;


  /*
   * 有些客户端会保留配置里的外层引号
   */

  if (
    /^[\"'].*[\"']$/.test(arg)
  ) {

    arg =
      arg.slice(
        1,
        -1
      );
  }


  /*
   * Loon JSON argument
   */

  if (
    arg.charAt(0) === "{"
  ) {

    try {

      return String(
        JSON.parse(arg).tokens ||
        ""
      );

    } catch (e) {}
  }


  /*
   * Surge：
   *
   * tokens=xxx&foo=bar
   */

  var pairs =
    arg.split("&");


  for (
    var i = 0;
    i < pairs.length;
    i++
  ) {

    var idx =
      pairs[i].indexOf("=");


    if (
      idx > 0 &&
      pairs[i].slice(
        0,
        idx
      ) === "tokens"
    ) {

      var value =
        pairs[i].slice(
          idx + 1
        );


      try {

        return decodeURIComponent(
          value
        );

      } catch (e) {

        return value;
      }
    }
  }


  /*
   * 直接把整串当 token
   */

  if (
    arg.indexOf(
      "pgnfw_"
    ) === 0
  ) {

    return arg;
  }


  return "";
}



/* =========================================================
 * 模块参数：test_proxy / retry_count / test_url
 * 不配置 test_proxy 时只执行原来的自动加白。
 * ======================================================= */
function getArgumentOption(name) {
  if (typeof $argument === "undefined" || $argument === null) return "";
  if (typeof $argument === "object") {
    return $argument[name] === undefined ? "" : String($argument[name]);
  }
  if (typeof $argument !== "string") return "";
  var arg = $argument.trim();
  if (/^["'].*["']$/.test(arg)) arg = arg.slice(1, -1);
  if (arg.charAt(0) === "{") {
    try {
      var obj = JSON.parse(arg);
      return obj[name] === undefined ? "" : String(obj[name]);
    } catch (e) {}
  }
  // Only recognized argument keys split values; proxy names and test URLs
  // may legitimately contain '&'.
  var keyPattern = /(?:^|&)(tokens|test_proxy|retry_count|test_url|log_level|trigger)=/g;
  var fields = [];
  var match;
  while ((match = keyPattern.exec(arg)) !== null) {
    fields.push({ name: match[1], start: match.index, from: keyPattern.lastIndex });
  }
  for (var i = 0; i < fields.length; i++) {
    if (fields[i].name !== name) continue;
    var end = (i + 1 < fields.length) ? fields[i + 1].start : arg.length;
    var value = arg.slice(fields[i].from, end);
    try { return decodeURIComponent(value); } catch (e) { return value; }
  }
  return "";
}

function getProxyTestConfig() {
  var proxy = getArgumentOption("test_proxy").trim();
  var cfg = {
    enabled: !!proxy,
    proxy: proxy,
    url: getArgumentOption("test_url").trim() || DEFAULT_PROXY_TEST_URL,
    retryCount: 0,
    error: ""
  };
  if (!cfg.enabled) return cfg;

  if (!isSurge) {
    cfg.error = "指定代理测试仅支持 Surge，其他客户端请留空 test_proxy";
    return cfg;
  }
  if (/^(DIRECT|REJECT|REJECT-TINYGIF)$/i.test(proxy)) {
    cfg.error = "test_proxy 请填写 Surge 中实际的代理节点名称，不要填写 DIRECT/REJECT";
    return cfg;
  }
  var rawCount = getArgumentOption("retry_count").trim() || "3";
  if (!/^\d+$/.test(rawCount) || Number(rawCount) > MAX_PROXY_RETRIES) {
    cfg.error = "retry_count 必须为 0-" + MAX_PROXY_RETRIES + " 的整数（额外加白次数）";
    return cfg;
  }
  cfg.retryCount = Number(rawCount);
  if (!/^https?:\/\/[^\s]+$/i.test(cfg.url) ||
      cfg.url.indexOf("#") >= 0 || /[\s]/.test(cfg.url)) {
    cfg.error = "test_url 必须是合法的 HTTP(S) 测试地址";
  }
  return cfg;
}

/* =========================================================
 * 蜂窝网络判断
 * ======================================================= */

function onCellular() {

  try {

    var iface =
      (
        $network.v4 &&
        $network.v4.primaryInterface
      ) ||
      (
        $network.v6 &&
        $network.v6.primaryInterface
      ) ||
      "";


    return (
      iface.indexOf(
        "pdp_ip"
      ) === 0
    );

  } catch (e) {

    return false;
  }
}


/* =========================================================
 * IP /24 判断
 * ======================================================= */

function sameC24(
  a,
  b
) {

  if (
    !a ||
    !b
  ) {
    return false;
  }


  a = String(a);
  b = String(b);


  if (
    a === b
  ) {
    return true;
  }


  /*
   * 两边都是精确 IP，
   * 且不相等，则直接 false。
   */

  if (
    a.slice(-3) !== "/24" &&
    b.slice(-3) !== "/24"
  ) {

    return false;
  }


  var pa =
    a
      .replace("/24", "")
      .split(".");


  var pb =
    b
      .replace("/24", "")
      .split(".");


  return (
    pa.length === 4 &&
    pb.length === 4 &&
    pa[0] === pb[0] &&
    pa[1] === pb[1] &&
    pa[2] === pb[2]
  );
}


/* =========================================================
 * 历史记录
 * ======================================================= */

function readHistory(key) {

  try {

    var h =
      JSON.parse(
        storeRead(key) ||
        "[]"
      );


    var cutoff =
      Date.now() -
      HIST_WINDOW_MS;


    return h.filter(
      function (e) {

        return (
          e &&
          e.ts >
          cutoff
        );
      }
    );

  } catch (e) {

    return [];
  }
}


/* =========================================================
 * 判断某个白名单 IP 是否曾由蜂窝网络加入
 * ======================================================= */

function wasCellular(
  ip,
  hist
) {

  for (
    var i = 0;
    i < hist.length;
    i++
  ) {

    if (
      hist[i].src === "cell" &&
      sameC24(
        hist[i].ip,
        ip
      )
    ) {

      return true;
    }
  }

  return false;
}


/* =========================================================
 * API 调用
 * ======================================================= */

function apiCall(
  token,
  slot,
  logTag
) {

  var url =
    API_BASE +
    encodeURIComponent(token) +
    "/add";


  if (
    slot !== null &&
    slot !== undefined &&
    slot !== ""
  ) {

    url +=
      "?slot=" +
      encodeURIComponent(
        slot
      );
  }


  var opts = {

    url: url,

    headers: {
      "Content-Type":
        "application/json"
    },

    body: ""
  };


  /*
   * Surge 下再做一层保险：
   *
   * 即使主配置规则未来发生变化，
   * po0 API 请求仍然强制 DIRECT。
   */

  if (isSurge) {

    opts.policy =
      "DIRECT";
  }


  if (
    REQUEST_TIMEOUT !== null
  ) {

    opts.timeout =
      REQUEST_TIMEOUT;
  }


  return httpRequest(
    "POST",
    opts,
    1,
    logTag
  ).then(
    function (r) {

      if (r.error) {

        return {
          error: redactSensitive(r.error),
          httpStatus: r.status || null
        };
      }


      var data = null;


      try {

        data =
          JSON.parse(
            r.body
          );

      } catch (e) {}


      /*
       * 固定槽位冲突
       */

      if (
        r.status === 403
      ) {

        return {

          error:
            "槽位冲突：本机 IP 已在其它槽位，请先去 UI 删除",

          conflict:
            true,

          currentIp:
            data &&
            data.currentIp,
          httpStatus: r.status
        };
      }


      /*
       * 正确处理所有 HTTP 非 2xx
       */

      if (
        r.status &&
        (
          r.status < 200 ||
          r.status >= 300
        )
      ) {

        var detail = "";


        if (data) {

          detail =
            data.message ||
            data.error ||
            data.msg ||
            data.code ||
            "";

          if (
            typeof detail === "object"
          ) {

            try {

              detail =
                JSON.stringify(
                  detail
                );

            } catch (e) {

              detail =
                String(detail);
            }
          }

        } else if (r.body) {

          detail =
            String(
              r.body
            ).slice(
              0,
              100
            );
        }


        return {

          error:
            "HTTP " +
            r.status +
            (
              detail
                ? " · " + detail
                : ""
            ),

          currentIp:
            data &&
            data.currentIp,
          httpStatus: r.status
        };
      }


      if (!data) {

        return {

          error:
            "响应异常: " +
            redactSensitive(String(r.body).slice(0, 100)),
          httpStatus: r.status
        };
      }


      /*
       * whitelist 新版：
       *
       * [
       *   {
       *      ip,
       *      slot
       *   }
       * ]
       *
       * 旧版：
       *
       * [
       *   "1.2.3.0/24"
       * ]
       */

      var raw =
        Array.isArray(
          data.whitelist
        )
          ? data.whitelist
          : [];


      data.slotOf = {};


      raw.forEach(
        function (e) {

          if (
            e &&
            typeof e === "object" &&
            e.ip &&
            e.slot !== null &&
            e.slot !== undefined
          ) {

            data.slotOf[
              e.ip
            ] =
              e.slot;
          }
        }
      );


      data.whitelist =
        raw.map(
          function (e) {

            return (
              e &&
              typeof e === "object"
            )
              ? e.ip
              : e;
          }
        ).filter(
          function (ip) {

            return !!ip;
          }
        );


      data.httpStatus = r.status || null;

      data.applied =
        data.enabled === true &&
        data.whitelist.some(
          function (ip) {

            return sameC24(
              ip,
              data.currentIp
            );
          }
        );


      return data;
    }
  );
}


/* =========================================================
 * 单 token 加白
 * ======================================================= */

function ensureWhitelisted(
  item,
  index
) {

  /*
   * 不再根据 token 顺序保存状态。
   *
   * token 调换顺序：
   *
   * A,B
   *
   * ↓
   *
   * B,A
   *
   * 不会导致历史记录串号。
   */

  var tokenId =
    hashString(
      item.token
    );


  var kvState =
    STORE_PREFIX +
    "state_" +
    tokenId;


  var kvHist =
    STORE_PREFIX +
    "hist_" +
    tokenId;


  var cellular =
    onCellular();


  var ctx = {

    kvState:
      kvState,

    kvHist:
      kvHist,

    slot:
      item.slot,

    index:
      index
  };


  /*
   * 服务端对重复 IP 幂等，
   * 无需提前 GET 查询。
   */

  return apiCall(
    item.token,
    item.slot,
    "token#" + (index + 1)
  ).then(
    function (st) {

      if (
        st.applied &&
        st.currentIp
      ) {

        var hist =
          readHistory(
            kvHist
          );


        var alreadyRecorded =
          hist.some(
            function (e) {

              return (
                sameC24(
                  e.ip,
                  st.currentIp
                ) &&
                e.src ===
                  (
                    cellular
                      ? "cell"
                      : "fixed"
                  )
              );
            }
          );


        if (
          !alreadyRecorded
        ) {

          hist.push({

            ip:
              st.currentIp,

            src:
              cellular
                ? "cell"
                : "fixed",

            ts:
              Date.now()
          });


          /*
           * 最多保存最近 10 条
           */

          storeWrite(
            JSON.stringify(
              hist.slice(-10)
            ),
            kvHist
          );
        }
      }


      ctx.st = st;

      return ctx;
    }
  );
}



/* =========================================================
 * Surge 原生代理测试：经 policy 指定的节点发送 HTTP HEAD。
 * 不走 ping API，不需要 ICMP 服务；成功标准：默认 URL 返回 204，
 * 自定义 URL 返回 2xx/3xx。代理网络失败则重试加白。
 * ======================================================= */
function testProxyConnection(config) {
  if (typeof $httpClient === "undefined" || typeof $httpClient.head !== "function") {
    return Promise.resolve({ ok: false, fatal: true, error: "当前客户端没有 $httpClient.head 接口" });
  }
  var opts = {
    url: config.url,
    policy: config.proxy,
    timeout: 5,
    "auto-redirect": false,
    headers: { "Cache-Control": "no-cache", "Pragma": "no-cache" }
  };
  var started = Date.now();
  return httpRequestOnce("HEAD", opts).then(function (r) {
    var latency = Date.now() - started;
    if (r.error) {
      var message = String(r.error);
      var fatal = /unknown policy|invalid policy|policy not found|no such policy|不存在的策略|未找到策略/i.test(message);
      return { ok: false, fatal: fatal, error: message, latency: latency };
    }
    var code = Number(r.status);
    if (!code) return { ok: false, error: "未收到 HTTP 状态码", latency: latency };
    var isDefault = config.url === DEFAULT_PROXY_TEST_URL;
    var ok = isDefault ? code === 204 : (code >= 200 && code < 400);
    return {
      ok: ok,
      code: code,
      latency: latency,
      error: ok ? "" : ("HTTP " + code + (isDefault ? "（期望 204）" : ""))
    };
  });
}

function ensureAndVerify(item, index, config) {
  var requests = 0;
  var tag = "token#" + (index + 1);
  var maxRequests = config.enabled ? config.retryCount + 1 : 1;
  var slotLabel = item.slot === null || item.slot === undefined ? "auto" : String(item.slot);
  function attempt() {
    requests++;
    var attemptStartedAt = Date.now();
    logEvent("DETAIL", "加白/开始", tag + " 第 " + requests + "/" + maxRequests +
      " 轮；POST /api/firewall/[REDACTED]/add；slot=" + slotLabel +
      "；加白 API 策略=" + (isSurge ? "DIRECT" : "客户端路由"));
    return ensureWhitelisted(item, index).then(function (ctx) {
      ctx.addRequests = requests;
      ctx.proxyConfigured = config.enabled;
      ctx.proxyName = config.proxy;
      var st = ctx.st || {};
      var apiDuration = Date.now() - attemptStartedAt;
      ctx.apiDuration = apiDuration;
      if (!st.applied) {
        logEvent("WARN", "加白/失败", tag + " 轮次=" + requests +
          " HTTP=" + (st.httpStatus || "-") +
          " duration=" + apiDuration + "ms" +
          " currentIp=" + (st.currentIp || "-") +
          " enabled=" + st.enabled +
          " reason=" + (st.error || "服务端未确认加白生效") +
          "；跳过本轮代理检测");
        return ctx;
      }

      logEvent("DETAIL", "加白/成功", tag + " 轮次=" + requests +
        " HTTP=" + (st.httpStatus || "-") +
        " duration=" + apiDuration + "ms" +
        " currentIp=" + (st.currentIp || "-") +
        " whitelist=" + ((st.whitelist || []).join(",") || "-") +
        " slots=" + (st.whitelist || []).map(function (ip) {
          return (st.slotOf && st.slotOf[ip] !== undefined) ? ip + "@" + st.slotOf[ip] : ip;
        }).join(",") +
        " count=" + (st.whitelist ? st.whitelist.length : 0) +
        "/" + (st.limit === undefined ? "?" : st.limit));
      if (!config.enabled) {
        logEvent("DETAIL", "代理/跳过", tag + " test_proxy 未配置，仅加白");
        return ctx;
      }

      logEvent("DETAIL", "代理/开始", tag + " 第 " + requests +
        " 次 HEAD policy=" + config.proxy +
        " url=" + safeTestUrl(config.url) + " timeout=5s");
      return testProxyConnection(config).then(function (result) {
        ctx.proxyTest = result;
        logEvent(result.ok ? "DETAIL" : "WARN", "代理/结果", tag +
          " policy=" + config.proxy +
          " result=" + (result.ok ? "PASS" : "FAIL") +
          " HTTP=" + (result.code || "-") +
          " latency=" + (result.latency === undefined ? "-" : result.latency) + "ms" +
          (result.error ? " reason=" + result.error : ""));
        if (result.ok) {
          logEvent("DETAIL", "流程/结束", tag + " 代理已可用，停止重试；加白轮次=" + requests);
          return ctx;
        }
        if (result.fatal) {
          logEvent("WARN", "流程/停止", tag + " 检测环境或策略配置错误，不再盲目重试");
          return ctx;
        }
        if (requests > config.retryCount) {
          logEvent("WARN", "流程/停止", tag + " 已达到额外重试次数 " +
            config.retryCount + "，本轮结束；后续 cron 或网络事件将再次尝试");
          return ctx;
        }
        logEvent("BRIEF", "重试", "⚠️ " + config.proxy + " 连接失败，准备第 " +
          (requests + 1) + "/" + maxRequests + " 次加白");
        logEvent("WARN", "流程/重试", tag + " 节点仍不可用，" +
          PROXY_RETRY_DELAY_MS + "ms 后重新请求 po0 加白；下一轮 " +
          (requests + 1) + "/" + maxRequests);
        return delay(PROXY_RETRY_DELAY_MS).then(attempt);
      });
    });
  }
  return attempt();
}

function describeProxyTest(ctx) {
  if (!ctx.proxyConfigured) return "";
  if (!ctx.proxyTest) return "\n    ⚠️ 代理未测试（加白 API 未成功）";
  var p = ctx.proxyTest;
  if (p.ok) {
    return "\n    ✅ 代理 " + ctx.proxyName + " 可用（HTTP " + p.code +
      " · " + p.latency + "ms）· 加白 " + ctx.addRequests + " 次";
  }
  return "\n    ❌ 代理 " + ctx.proxyName + " 测试失败：" + p.error +
    " · 加白 " + ctx.addRequests + " 次";
}

function briefResult(results, config, okCount) {
  var allOk = okCount === results.length;
  var label = RUN_TRIGGER === "network-changed" ? "网络变化" :
    RUN_TRIGGER === "cron" ? "定时检查" :
    RUN_TRIGGER === "engine-started" ? "Surge 启动" : "手动执行";
  var lead = (allOk ? "✅ " : "❌ ") + label + "｜";
  var lines = results.map(function(ctx, index) {
    var st = ctx.st || {}, p = ctx.proxyTest;
    var success = !!st.applied && (!config.enabled || (p && p.ok));
    var line = (results.length > 1 ? "#" + (index + 1) + " " : "") +
      (success ? "加白成功" : (st.applied ? "代理不通（已加白）" : "加白失败"));
    if (st.currentIp) line += " · 出口 " + st.currentIp;
    if (st.whitelist && st.limit !== undefined) line += " · 白名单 " + st.whitelist.length + "/" + st.limit;
    if (!st.applied) line += "（" + (st.error || "服务器未确认生效") + "）";
    else if (config.enabled) line += " · " + config.proxy +
      (p && p.ok ? " " + p.latency + "ms" : " 不可用（" + String((p && p.error) || "未检测").replace(/timeout|timed out/gi, "超时") + "）");
    if (ctx.addRequests > 1) line += " · 加白 " + ctx.addRequests + " 次";
    return line;
  });
  return lead + (results.length > 1 ? okCount + "/" + results.length + " 成功\n" : "") + lines.join("\n");
}

/* =========================================================
 * 输出单 token 状态
 * ======================================================= */

function describe(
  index,
  ctx
) {

  var st =
    ctx.st;


  var pin =
    (
      ctx.slot !== null &&
      ctx.slot !== undefined &&
      ctx.slot !== ""
    )
      ? " 📌" + ctx.slot
      : "";


  var head =
    "#" +
    (index + 1) +
    pin +
    " ";


  if (st.error) {

    return (
      head +
      "❌ " +
      st.error
    );
  }


  if (
    st.enabled === false
  ) {

    return (
      head +
      "⚠️ 防火墙未启用"
    );
  }


  if (
    !st.applied
  ) {

    return (
      head +
      "❌ 加白未生效 " +
      st.whitelist.length +
      "/" +
      (
        st.limit !== undefined
          ? st.limit
          : "?"
      )
    );
  }


  var hist =
    readHistory(
      ctx.kvHist
    );


  var slotOf =
    st.slotOf ||
    {};


  var ips =
    st.whitelist
      .map(
        function (ip) {

          var slotTag =
            slotOf[ip] !== undefined
              ? " 📌" + slotOf[ip]
              : "";


          var cellTag =
            wasCellular(
              ip,
              hist
            )
              ? " 📶"
              : "";


          var currentTag =
            sameC24(
              ip,
              st.currentIp
            )
              ? " ←"
              : "";


          return (
            ip +
            slotTag +
            cellTag +
            currentTag
          );
        }
      )
      .join("\n    ");


  return (
    head +
    "✅ " +
    st.whitelist.length +
    "/" +
    (
      st.limit !== undefined
        ? st.limit
        : "?"
    ) +
    "\n    " +
    ips +
    describeProxyTest(ctx)
  );
}


/* =========================================================
 * token 解析
 * ======================================================= */

function parseTokens(raw) {

  var parts =
    String(
      raw ||
      ""
    )
      .split(
        /[,|;、\s]+/
      )
      .map(
        function (s) {

          return s.trim();
        }
      )
      .filter(
        function (s) {

          return (
            s.indexOf(
              "pgnfw_"
            ) === 0
          );
        }
      );


  var items = [];
  var errors = [];


  /*
   * exactSeen：
   *
   * 相同：
   *
   * token@0
   * token@0
   *
   * 自动去重。
   */

  var exactSeen = {};


  /*
   * tokenSlot：
   *
   * 检测：
   *
   * token@0
   * token@1
   *
   * 或：
   *
   * token
   * token@0
   *
   * 这类歧义配置。
   */

  var tokenSlot = {};


  for (
    var i = 0;
    i < parts.length;
    i++
  ) {

    var text =
      parts[i];


    var token =
      text;


    var slot =
      null;


    var at =
      text.lastIndexOf("@");


    if (
      at !== -1
    ) {

      token =
        text.slice(
          0,
          at
        );


      var slotText =
        text.slice(
          at + 1
        );


      /*
       * @slot 必须是纯数字
       */

      if (
        !/^\d+$/.test(
          slotText
        )
      ) {

        errors.push(
          "第 " +
          (i + 1) +
          " 个 token 的槽位格式错误，@ 后必须为非负整数"
        );

        continue;
      }


      slot =
        parseInt(
          slotText,
          10
        );
    }


    if (
      token.indexOf(
        "pgnfw_"
      ) !== 0
    ) {

      continue;
    }


    var slotKey =
      slot === null
        ? "slotless"
        : String(slot);


    /*
     * 相同 token 出现不同 slot 配置
     */

    if (
      Object.prototype.hasOwnProperty.call(
        tokenSlot,
        token
      ) &&
      tokenSlot[token] !==
        slotKey
    ) {

      errors.push(
        "同一 token 重复配置了不同槽位，请只保留一种配置"
      );

      continue;
    }


    tokenSlot[token] =
      slotKey;


    var exactKey =
      token +
      "@" +
      slotKey;


    /*
     * 完全相同的配置自动去重
     */

    if (
      exactSeen[
        exactKey
      ]
    ) {

      continue;
    }


    exactSeen[
      exactKey
    ] =
      true;


    items.push({

      token:
        token,

      slot:
        slot
    });
  }


  return {

    items:
      items,

    errors:
      errors
  };
}


/* =========================================================
 * 主流程
 * ======================================================= */

var rawTokens =
  getArgumentTokens() ||
  storeRead(TOKENS_KEY) ||
  INLINE_TOKENS ||
  "";


var parsed =
  parseTokens(
    rawTokens
  );

var proxyConfig = getProxyTestConfig();
var configuredLogLevel = getArgumentOption("log_level").trim().toLowerCase();
var logLevelError = configuredLogLevel && !/^(simple|summary|detail|debug|off)$/.test(configuredLogLevel)
  ? "log_level 必须为 simple、debug 或 off" : "";
// 旧参数 detail 自动使用简洁日志，debug 才输出详细排障信息。
LOG_LEVEL = configuredLogLevel === "off" ? "off" :
  configuredLogLevel === "debug" ? "debug" : "summary";
RUN_TRIGGER = getArgumentOption("trigger") || getEventName() || "manual/unknown";

logEvent("INFO", "启动", "trigger=" + RUN_TRIGGER +
  " iface=" + (onCellular() ? "cellular" : "wifi/other") +
  " tokens=" + parsed.items.length +
  " proxy=" + (proxyConfig.enabled ? proxyConfig.proxy : "disabled") +
  " test_url=" + (proxyConfig.enabled ? safeTestUrl(proxyConfig.url) : "-") +
  " extra_retries=" + proxyConfig.retryCount +
  " log_level=" + LOG_LEVEL);


/* ---------- 参数错误 ---------- */

if (logLevelError || proxyConfig.error) {
  var validationError = logLevelError || proxyConfig.error;
  logEvent("BRIEF", "配置", "❌ 配置错误：" + validationError);
  logEvent("ERROR", "配置", validationError);
  writeLogbookSummary("参数配置错误：" + validationError);
  saveRunSummary({ run_id: RUN_ID, at: new Date().toISOString(), trigger: RUN_TRIGGER,
    ok: false, duration_ms: Date.now() - RUN_STARTED_AT, error: validationError });
  notify("po0 防火墙加白", "模块参数配置错误", validationError);
  finish("po0 加白：参数错误", validationError, false);

} else if (
  parsed.errors.length > 0
) {

  var configError =
    parsed.errors.join(
      "\n"
    );
  logEvent("BRIEF", "配置", "❌ Token 配置错误：" + configError);
  logEvent("ERROR", "配置", configError);
  writeLogbookSummary("Token 配置错误：" + configError);
  saveRunSummary({ run_id: RUN_ID, at: new Date().toISOString(), trigger: RUN_TRIGGER,
    ok: false, duration_ms: Date.now() - RUN_STARTED_AT, error: configError });


  notify(
    "po0 防火墙加白",
    "token 参数配置错误",
    configError
  );


  finish(
    "po0 加白：参数错误",
    configError,
    false
  );


/* ---------- 未配置 token ---------- */

} else if (
  parsed.items.length === 0
) {

  logEvent("BRIEF", "配置", "❌ 未配置有效 Token");
  logEvent("ERROR", "配置", "未配置有效 token，终止执行");
  writeLogbookSummary("未配置有效 Token");
  saveRunSummary({ run_id: RUN_ID, at: new Date().toISOString(), trigger: RUN_TRIGGER,
    ok: false, duration_ms: Date.now() - RUN_STARTED_AT, error: "未配置有效 token" });
  notify(
    "po0 防火墙加白",
    "未配置 token",
    "模块参数 tokens / 存储 key po0fw_tokens / INLINE_TOKENS 三选一填写 pgnfw_ token"
  );


  finish(
    "po0 加白：未配置 token",
    "请填入 pgnfw_ token，多个使用英文逗号 , 分隔",
    false
  );


/* ---------- 正常执行 ---------- */

} else {

  var tokens =
    parsed.items;


  var eventName = RUN_TRIGGER;


  var startDelay =
    eventName === "network-changed"
      ? NETWORK_CHANGED_DELAY_MS
      : 0;


  if (
    startDelay > 0
  ) {

    logEvent("DETAIL", "网络", "network-changed，等待 " + startDelay + "ms 路由稳定后加白");
  }


  delay(
    startDelay
  ).then(
    function () {

      return Promise.all(
        tokens.map(
          function (
            t,
            i
          ) {

            return ensureAndVerify(
              t,
              i,
              proxyConfig
            );
          }
        )
      );
    }
  ).then(
    function (results) {

      var okCount = 0;
      var lines = [];
      var changed = false;


      /*
       * 收集出口 IP，
       * 多 token 情况下避免只显示最后一个。
       */

      var exitIps = [];
      var runItems = [];


      for (
        var i = 0;
        i < results.length;
        i++
      ) {

        var st =
          results[i].st;


        if (
          st.applied &&
          (!proxyConfig.enabled || (results[i].proxyTest && results[i].proxyTest.ok))
        ) {

          okCount++;
        }


        if (
          st.currentIp &&
          exitIps.indexOf(
            st.currentIp
          ) === -1
        ) {

          exitIps.push(
            st.currentIp
          );
        }


        lines.push(
          describe(
            i,
            results[i]
          )
        );
        var p = results[i].proxyTest;
        var itemOk = !!st.applied && (!proxyConfig.enabled || (p && p.ok));
        var itemError = st.error || (proxyConfig.enabled && !p ? "代理未检测" :
          (p && !p.ok ? p.error : ""));
        logEvent(itemOk ? "INFO" : "WARN", "Token/小结", "token#" + (i + 1) +
          " status=" + (itemOk ? "PASS" : "FAIL") +
          " ip=" + (st.currentIp || "-") +
          " api_http=" + (st.httpStatus || "-") +
          " api_ok=" + !!st.applied +
          " slot=" + (results[i].slot === null ? "auto" : results[i].slot) +
          " add_rounds=" + (results[i].addRequests || 0) +
          " proxy_http=" + (p ? (p.code || "-") : "-") +
          " proxy_ms=" + (p ? p.latency : "-") +
          (itemError ? " reason=" + itemError : ""));
        runItems.push({
          token_index: i + 1,
          slot: results[i].slot,
          ok: itemOk,
          ip: st.currentIp || null,
          api_http: st.httpStatus || null,
          api_ok: !!st.applied,
          add_rounds: results[i].addRequests || 0,
          whitelist_count: st.whitelist ? st.whitelist.length : null,
          limit: st.limit === undefined ? null : st.limit,
          proxy_ok: p ? !!p.ok : null,
          proxy_http: p ? (p.code || null) : null,
          proxy_ms: p && p.latency !== undefined ? p.latency : null,
          error: redactSensitive(itemError)
        });


        /*
         * 成功状态持久化：
         *
         * currentIp + applied
         *
         * key 已经基于 token hash，
         * 不再依赖 token 顺序。
         */

        var state =
          (
            st.currentIp ||
            "?"
          ) +
          "|" +
          (
            st.applied
              ? "1"
              : "0"
          ) +
          (proxyConfig.enabled
              ? ("|proxy=" + (results[i].proxyTest ?
                   (results[i].proxyTest.ok ? "1" : "0") : "skip"))
              : "");


        if (
          storeRead(
            results[i].kvState
          ) !== state
        ) {

          storeWrite(
            state,
            results[i].kvState
          );

          changed =
            true;
        }
      }


      var allOk =
        okCount ===
        results.length;


      var exitText =
        exitIps.length
          ? exitIps.join(",")
          : "?";


      var title =
        "po0 加白 " +
        okCount +
        "/" +
        results.length +
        " · 出口 " +
        exitText +
        (
          onCellular()
            ? " 📶"
            : ""
        ) +
        (proxyConfig.enabled ? " · 代理 " + proxyConfig.proxy : "");


      var content =
        lines.join(
          "\n"
        );


      /*
       * 成功：
       * 仅 IP / 状态变化时通知。
       *
       * 失败：
       * 每次通知。
       *
       * 防止连续失败时 changed=false 导致错误被静默吞掉。
       */

      var totalDuration = Date.now() - RUN_STARTED_AT;
      var needNotify = changed || !allOk;
      logEvent("BRIEF", "结果", briefResult(results, proxyConfig, okCount));
      logEvent(allOk ? "INFO" : "WARN", "本轮汇总",
        "trigger=" + RUN_TRIGGER + " passed=" + okCount + "/" + results.length +
        " duration=" + totalDuration + "ms" +
        " exitIps=" + exitText +
        " stateChanged=" + changed + " notify=" + needNotify);
      saveRunSummary({
        run_id: RUN_ID, at: new Date().toISOString(), trigger: RUN_TRIGGER,
        duration_ms: totalDuration, ok: allOk, passed: okCount,
        total: results.length, proxy: proxyConfig.enabled ? proxyConfig.proxy : null,
        test_url: proxyConfig.enabled ? safeTestUrl(proxyConfig.url) : null,
        state_changed: changed, notified: needNotify, items: runItems
      });
      if (
        needNotify
      ) {
        writeLogbookSummary(briefResult(results, proxyConfig, okCount));
        notify(
          "po0 防火墙加白",
          title,
          content
        );
      }


      finish(
        title,
        content,
        allOk
      );
    }
  ).catch(
    function (e) {

      var message =
        String(
          e &&
          e.message
            ? e.message
            : e
        );


      logEvent("BRIEF", "异常", "❌ 脚本异常：" + message);
      logEvent("ERROR", "脚本异常", message);
      writeLogbookSummary("脚本异常：" + message);
      saveRunSummary({ run_id: RUN_ID, at: new Date().toISOString(), trigger: RUN_TRIGGER,
        ok: false, duration_ms: Date.now() - RUN_STARTED_AT, error: redactSensitive(message) });
      notify(
        "po0 防火墙加白",
        "脚本异常",
        redactSensitive(message)
      );


      finish(
        "po0 加白：脚本异常",
        redactSensitive(message),
        false
      );
    }
  );
}
