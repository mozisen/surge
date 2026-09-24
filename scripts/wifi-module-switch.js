const TARGET_WIFIS = [

  "mozi",

  "weeland",

  "mozi-5G"

];

const MODULE_NAME = "po0 防火墙自动加白";

const wifi = $network.wifi;

const ssid = wifi ? wifi.ssid : null;

// 当前 WiFi 是否属于需要关闭模块的 WiFi

const isTargetWiFi = ssid && TARGET_WIFIS.indexOf(ssid) !== -1;

// 命中指定 WiFi → 关闭模块

// 其他 WiFi / 4G / 5G → 开启模块

const shouldEnable = !isTargetWiFi;

console.log("当前网络：" + (ssid ? "WiFi - " + ssid : "蜂窝网络 / 无 WiFi"));

console.log("目标 WiFi：" + (isTargetWiFi ? "命中" : "未命中"));

console.log(MODULE_NAME + " → " + (shouldEnable ? "开启" : "关闭"));

const body = {};

body[MODULE_NAME] = shouldEnable;

$httpAPI("POST", "/v1/modules", body, function(result) {

  console.log("API返回：" + JSON.stringify(result));

  if (isTargetWiFi) {

    console.log("已连接 " + ssid + " → 关闭模块");

  } else {

    console.log("未连接指定 WiFi → 开启模块");

  }

  $done();

});