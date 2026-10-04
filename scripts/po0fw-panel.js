/* po0fw read-only Surge panel. GET only; no whitelist mutation. */
(function () {
  'use strict';
  var finished = false;
  function done(result) { if (!finished) { finished = true; $done(result); } }
  function error(message) { done({title: 'po0fw · 查询失败', content: message + '\n未展示历史数据，请稍后刷新。', style: 'error'}); }
  function args(text) {
    var result = {};
    String(text || '').split('&').forEach(function (part) {
      var at = part.indexOf('=');
      if (at >= 0) result[part.slice(0, at)] = decodeURIComponent(part.slice(at + 1));
    });
    return result;
  }
  function clean(text) { return String(text).replace(/[\r\n\t]/g, ' '); }
  function integer(value) { return typeof value === 'number' && isFinite(value) && Math.floor(value) === value; }
  function render(data) {
    if (!data || !Array.isArray(data.whitelist)) throw new Error('schema');
    var list = data.whitelist;
    var limit = Number(data.limit);
    var knownLimit = data.limit !== null && data.limit !== undefined && integer(limit) && limit >= 0;
    var current = typeof data.currentIp === 'string' ? data.currentIp : '';
    var fixed = [], fifo = [], other = [], hit = false;
    list.forEach(function (entry) {
      if (!entry || typeof entry.ip !== 'string' || !entry.ip) throw new Error('entry');
      if (entry.ip === current) hit = true;
      if (entry.slot === null) fifo.push(entry);
      else if ((typeof entry.slot === 'number' || (typeof entry.slot === 'string' && /^\d+$/.test(entry.slot))) && integer(Number(entry.slot)) && Number(entry.slot) >= 0) fixed.push(entry);
      else other.push(entry);
    });
    fixed.sort(function (a, b) { return Number(a.slot) - Number(b.slot); });
    var lines = ['占用 ' + list.length + '/' + (knownLimit ? limit : '?') + ' · 剩余 ' + (knownLimit ? Math.max(0, limit-list.length) : '?')];
    lines.push('本机出口：' + (current ? clean(current) : '接口未返回'));
    lines.push(current ? (hit ? '✓ 当前出口已在白名单' : '⚠ 当前出口未在白名单') : '当前出口命中状态未知');
    function row(label, entry) { lines.push((entry.ip === current ? '● ' : '○ ') + label + '  ' + clean(entry.ip)); }
    fixed.forEach(function (entry) { row('固定槽 ' + entry.slot, entry); });
    fifo.forEach(function (entry, index) { row('FIFO ' + (index + 1), entry); });
    other.forEach(function (entry, index) { row('未标注槽位 ' + (index + 1), entry); });
    if (!list.length) lines.push('白名单为空');
    lines.push('更新 ' + new Date().toLocaleTimeString());
    done({title: 'po0fw · 全部槽位', content: lines.join('\n'), style: current ? (hit ? 'good' : 'alert') : 'info'});
  }
  var config;
  try { config = args(typeof $argument === 'undefined' ? '' : $argument); }
  catch (_) { error('模块参数格式错误。'); return; }
  var token = String(config.token || '').trim().replace(/@\d+$/, '');
  if (!/^pgnfw_[A-Za-z0-9_-]+$/.test(token) || token === 'pgnfw_REPLACE_ME') {
    done({title: 'po0fw · 待配置', content: '请在模块 TOKEN 参数填写一个有效 token。\n显示此 token 对应的全部白名单记录。', style: 'info'}); return;
  }
  setTimeout(function () { error('查询超时，请检查网络或 API 可用性。'); }, 13000);
  try {
    $httpClient.get({
      url: 'https://124.221.69.228/api/firewall/' + encodeURIComponent(token),
      policy: 'DIRECT', timeout: 10, 'auto-redirect': false, 'auto-cookie': false,
      headers: {Accept: 'application/json'}
    }, function (err, response, body) {
      if (finished) return;
      if (err) { error('网络或 TLS 连接失败。'); return; }
      var status = Number(response && response.status);
      if (status === 401 || status === 403) { error('认证失败，请检查 TOKEN。'); return; }
      if (status < 200 || status >= 300 || !isFinite(status)) { error('接口返回 HTTP ' + status + '。'); return; }
      try { render(JSON.parse(body)); }
      catch (_) { error('接口数据格式不符合预期，无法确认槽位状态。'); }
    });
  } catch (_) { error('无法发起查询，请检查 Surge 脚本配置。'); }
}());
