/**
 * Surge WiFi 自动模块切换
 *
 * 模块参数格式：
 * mozi|weeland|mozi-5G
 *
 * 命中指定 WiFi：
 *   关闭「po0 防火墙自动加白」
 *
 * 未命中：
 *   开启「po0 防火墙自动加白」
 */

const MODULE_NAME = "po0 防火墙自动加白";

// ==============================
// 读取模块传入的 WiFi 参数
// ==============================

const argument =
  typeof $argument === "string"
    ? $argument
    : "";

// 使用 | 分割多个 WiFi
const TARGET_WIFIS = argument
  .split("|")
  .filter(item => item.length > 0);


// ==============================
// 获取当前 WiFi
// ==============================

const wifi = $network.wifi;

const ssid =
  wifi && wifi.ssid
    ? wifi.ssid
    : null;


// ==============================
// 判断当前 WiFi 是否命中
// ==============================

const isTargetWiFi =
  ssid !== null &&
  TARGET_WIFIS.indexOf(ssid) !== -1;


// ==============================
// 模块状态
// ==============================

// 命中指定 WiFi
// → 关闭模块
//
// 其他 WiFi / 4G / 5G
// → 开启模块

const shouldEnable = !isTargetWiFi;


// ==============================
// 日志
// ==============================

console.log("========== WiFi 模块切换 ==========");

console.log(
  "设定 WiFi：" +
  JSON.stringify(TARGET_WIFIS)
);

console.log(
  "当前网络：" +
  (ssid || "蜂窝网络 / 无 WiFi")
);

console.log(
  "WiFi 匹配：" +
  (isTargetWiFi ? "是" : "否")
);

console.log(
  MODULE_NAME +
  " → " +
  (shouldEnable ? "开启" : "关闭")
);


// ==============================
// 调用 Surge API
// ==============================

const body = {};

body[MODULE_NAME] = shouldEnable;

$httpAPI(
  "POST",
  "/v1/modules",
  body,
  function(result) {

    console.log(
      "API 返回：" +
      JSON.stringify(result)
    );

    if (isTargetWiFi) {

      console.log(
        "已连接 " +
        ssid +
        " → 关闭模块：" +
        MODULE_NAME
      );

    } else {

      console.log(
        "未连接指定 WiFi → 开启模块：" +
        MODULE_NAME
      );

    }

    $done();
  }
);