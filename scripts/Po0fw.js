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
 * - 可选 ICMP Ping 探针 + 失败后重复加白
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

// Surge JS 无原生 ICMP socket，委托给同出口的 Ping 探针。
var DEFAULT_PING_API = "http://127.0.0.1:18765/ping";
var PING_RETRY_DELAY_MS = 1800;
var MAX_PING_RETRIES = 5;


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
  attempt
) {

  attempt =
    attempt ||
    1;


  return httpRequestOnce(
    method,
    opts
  ).then(
    function (r) {

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


      return delay(
        HTTP_RETRY_DELAY_MS *
        attempt
      ).then(
        function () {

          return httpRequest(
            method,
            opts,
            attempt + 1
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
 * Surge 模块自定义参数：ping_ip / retry_count / ping_api / ping_key。
 * 不填 ping_ip 则维持原来的单次加白行为。
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
  var pairs = arg.split("&");
  for (var i = 0; i < pairs.length; i++) {
    var at = pairs[i].indexOf("=");
    if (at < 1 || pairs[i].slice(0, at) !== name) continue;
    var value = pairs[i].slice(at + 1);
    try { return decodeURIComponent(value); } catch (e) { return value; }
  }
  return "";
}
function isValidIPv4(ip) {
  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(ip)) return false;
  return ip.split(".").every(function (part) {
    return part.length > 0 && Number(part) >= 0 && Number(part) <= 255;
  });
}
function getPingConfig() {
  var ip = getArgumentOption("ping_ip").trim();
  var cfg = { enabled: !!ip, ip: ip, retryCount: 0, api: "", key: "", error: "" };
  if (!cfg.enabled) return cfg;
  if (!isValidIPv4(ip)) {
    cfg.error = "ping_ip 必须是合法的 IPv4 地址";
    return cfg;
  }
  var rawCount = getArgumentOption("retry_count").trim();
  if (rawCount === "") rawCount = "3";
  if (!/^\d+$/.test(rawCount) || Number(rawCount) > MAX_PING_RETRIES) {
    cfg.error = "retry_count 必须为 0-" + MAX_PING_RETRIES + " 的整数（额外加白次数）";
    return cfg;
  }
  cfg.retryCount = Number(rawCount);
  cfg.api = getArgumentOption("ping_api").trim() || DEFAULT_PING_API;
  cfg.key = getArgumentOption("ping_key").trim();
  if (!/^https?:\/\/[^\s]+$/i.test(cfg.api) || cfg.api.indexOf("#") !== -1) {
    cfg.error = "ping_api 必须是可访问的 HTTP(S) Ping 探针地址";
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
  slot
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
    opts
  ).then(
    function (r) {

      if (r.error) {

        return {
          error: r.error
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
            data.currentIp
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
            data.currentIp
        };
      }


      if (!data) {

        return {

          error:
            "响应异常: " +
            String(
              r.body
            ).slice(
              0,
              100
            )
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
    item.slot
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
 * 真正的 ICMP Ping 由可选的本地助手发起，HTTP 只传输检测结果。
 * 预期响应：{"ip":"1.2.3.4","ok":true/false}。
 * ======================================================= */
function probeIcmp(config) {
  var sep = config.api.indexOf("?") >= 0 ? "&" : "?";
  var opts = {
    url: config.api + sep + "ip=" + encodeURIComponent(config.ip) + "&_t=" + Date.now(),
    headers: { "Accept": "application/json" }
  };
  if (config.key) opts.headers["X-Ping-Key"] = config.key;
  if (isSurge) opts.policy = "DIRECT";
  if (isLoon || isQX) opts.timeout = 4000;
  else if (isSurgeFamily) opts.timeout = 4;
  return httpRequestOnce("GET", opts).then(function (r) {
    if (r.error) return { ok: false, error: "Ping 探针不可用：" + r.error };
    if (r.status !== 200) {
      return { ok: false, error: "Ping 探针 HTTP " + (r.status || "?") };
    }
    var data;
    try { data = JSON.parse(r.body); } catch (e) {
      return { ok: false, error: "Ping 探针响应不是 JSON" };
    }
    if (!data || data.ip !== config.ip || typeof data.ok !== "boolean") {
      return { ok: false, error: "Ping 探针响应格式不正确" };
    }
    return { ok: data.ok, error: "" };
  });
}
function ensureAndVerify(item, index, config) {
  var requests = 0;
  function attempt() {
    requests++;
    return ensureWhitelisted(item, index).then(function (ctx) {
      ctx.addRequests = requests;
      ctx.pingConfigured = config.enabled;
      ctx.pingTarget = config.ip;
      if (!config.enabled || !ctx.st.applied) return ctx;
      return probeIcmp(config).then(function (result) {
        ctx.ping = result;
        // 探针故障不能视为 Ping 不通，否则会盲目重复加白。
        if (result.ok || result.error || requests > config.retryCount) return ctx;
        return delay(PING_RETRY_DELAY_MS).then(attempt);
      });
    });
  }
  return attempt();
}
function describePing(ctx) {
  if (!ctx.pingConfigured) return "";
  if (!ctx.ping) return "\n    ⚠️ 未执行 Ping（加白 API 尚未成功）";
  if (ctx.ping.error) return "\n    ⚠️ " + ctx.ping.error;
  return "\n    " + (ctx.ping.ok ? "✅" : "❌") +
    " ICMP Ping " + ctx.pingTarget +
    (ctx.ping.ok ? " 通" : " 不通") +
    " · 加白请求 " + ctx.addRequests + " 次";
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
    describePing(ctx)
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

var pingConfig = getPingConfig();


/* ---------- 参数错误 ---------- */

if (pingConfig.error) {
  notify("po0 防火墙加白", "Ping 参数配置错误", pingConfig.error);
  finish("po0 加白：Ping 参数错误", pingConfig.error, false);

} else if (
  parsed.errors.length > 0
) {

  var configError =
    parsed.errors.join(
      "\n"
    );


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


  var eventName =
    getEventName();


  var startDelay =
    eventName === "network-changed"
      ? NETWORK_CHANGED_DELAY_MS
      : 0;


  if (
    startDelay > 0
  ) {

    console.log(
      "检测到 network-changed，等待 " +
      startDelay +
      "ms 后执行加白"
    );
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
              pingConfig
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


      for (
        var i = 0;
        i < results.length;
        i++
      ) {

        var st =
          results[i].st;


        if (
          st.applied &&
          (!pingConfig.enabled || (results[i].ping && results[i].ping.ok))
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
          (pingConfig.enabled
              ? ("|ping=" + (results[i].ping ?
                  (results[i].ping.error ? "error" :
                    (results[i].ping.ok ? "1" : "0")) : "skip"))
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
        (pingConfig.enabled ? " · Ping " + pingConfig.ip : "");


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

      if (
        changed ||
        !allOk
      ) {

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


      notify(
        "po0 防火墙加白",
        "脚本异常",
        message
      );


      finish(
        "po0 加白：脚本异常",
        message,
        false
      );
    }
  );
}
