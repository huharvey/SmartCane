'use strict';

const byId = id => document.getElementById(id);
const alarmNames = {
  NORMAL: '正常', CAUTION: '提醒', WARNING: '警告', DANGER: '危险',
  SUSPECTED_FALL: '疑似跌倒', FALL: '跌倒报警', SOS: 'SOS 求助'
};
const rhythmNames = {
  DISABLED: '未启用', NO_SENSOR: '模块离线', NO_FINGER: '请放置手指',
  COLLECTING: '采集中', MOTION_ARTIFACT: '请保持静止', INCONCLUSIVE: '信号不足',
  NORMAL: '节律规则', IRREGULAR: '节律不规则', SUSPECTED_AF: '疑似异常节律'
};
const eventNames = {
  SOS: 'SOS 求助', FALL: '跌倒报警', SUSPECTED_FALL: '疑似跌倒',
  RHYTHM_SCREENING_ALERT: '节律筛查提醒'
};

let renderedMapKey = '';
let lastStateAt = 0;

function setText(id, value) { byId(id).textContent = value; }

function optionalBoolean(object, key) {
  return object && Object.prototype.hasOwnProperty.call(object, key)
    ? Boolean(object[key]) : null;
}

function setBadge(id, state, okText, failText, waitingText) {
  const element = byId(id);
  const css = state === true ? 'ok' : state === false ? 'fail' : 'waiting';
  const label = state === true ? okText : state === false ? failText : waitingText;
  element.className = `badge ${css}`;
  element.replaceChildren(document.createElement('i'), document.createTextNode(label));
}

function setHealth(id, state, labels = {}) {
  const element = byId(id);
  let css = 'waiting';
  let label = labels.waiting || '等待';
  if (state === true || state === 'ok') { css = 'ok'; label = labels.ok || '正常'; }
  if (state === false || state === 'fail') { css = 'fail'; label = labels.fail || '异常'; }
  if (state === 'warn') { css = 'warn'; label = labels.warn || '注意'; }
  element.className = `health ${css}`;
  element.textContent = label;
}

function localTime(iso) {
  if (!iso) return '--';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '--' : date.toLocaleString('zh-CN', { hour12: false });
}

function duration(ms) {
  if (!Number.isFinite(Number(ms))) return '--';
  const seconds = Math.max(0, Math.floor(Number(ms) / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  if (days) return `${days}天 ${hours}小时`;
  if (hours) return `${hours}小时 ${minutes}分`;
  return `${minutes}分钟`;
}

function validCoordinate(gps) {
  const lat = Number(gps && gps.lat);
  const lon = Number(gps && gps.lon);
  return Boolean(gps && gps.valid && Number.isFinite(lat) && Number.isFinite(lon) &&
    lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180);
}

function updateMap(gps, mapConfigured) {
  const image = byId('amap-static-map');
  const placeholder = byId('map-placeholder');
  const link = byId('map-link');
  if (!validCoordinate(gps)) {
    renderedMapKey = '';
    image.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = '尚无可显示的位置';
    link.className = 'map-link disabled';
    link.removeAttribute('href');
    setText('map-note', '等待 GPS 定位；获得位置后显示高德静态地图。');
    return;
  }

  const lat = Number(gps.lat);
  const lon = Number(gps.lon);
  const source = gps.source === 'live' ? 'live' : 'last';
  setText('map-note', source === 'live'
    ? '实时定位；绿色标记为当前粗略位置，固定比例预览不可缩放。'
    : 'GPS 信号已中断；黄色标记为最后一次有效位置。');
  link.className = 'map-link';
  link.href = `https://uri.amap.com/marker?position=${lon.toFixed(6)},${lat.toFixed(6)}&name=SmartCane&coordinate=wgs84&callnative=0`;

  if (!mapConfigured) {
    image.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = '云服务器尚未配置高德静态地图 Key；经纬度与详细位置链接仍可使用。';
    return;
  }

  const mapKey = `${source}:${lat.toFixed(3)},${lon.toFixed(3)}`;
  if (renderedMapKey === mapKey && !image.hidden) return;
  renderedMapKey = mapKey;
  placeholder.hidden = false;
  placeholder.textContent = '正在加载高德地图…';
  image.hidden = true;
  image.onload = () => { image.hidden = false; placeholder.hidden = true; };
  image.onerror = () => {
    image.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = '高德地图加载失败；请检查云服务器网络与地图 Key 配置。';
  };
  image.src = `/api/map.png?v=${encodeURIComponent(mapKey)}`;
}

function renderEvents(events) {
  const list = byId('event-list');
  const records = Array.isArray(events) ? events : [];
  setText('event-count', records.length);
  if (!records.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = '暂无 SOS、跌倒或节律筛查事件';
    list.replaceChildren(empty);
    return;
  }

  const rows = records.map(record => {
    const payload = record && typeof record.payload === 'object' ? record.payload : {};
    const type = String(payload.event || 'EVENT');
    const gps = payload.gps && typeof payload.gps === 'object' ? payload.gps : {};
    const row = document.createElement('div');
    row.className = `event-row ${type.toLowerCase()}`;
    const mark = document.createElement('div');
    mark.className = 'event-mark';
    const body = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'event-title';
    title.textContent = eventNames[type] || type;
    const detail = document.createElement('div');
    detail.className = 'event-detail';
    detail.textContent = validCoordinate(gps)
      ? `位置 ${Number(gps.lat).toFixed(5)}, ${Number(gps.lon).toFixed(5)}`
      : '事件发生时无有效定位';
    body.append(title, detail);
    const time = document.createElement('div');
    time.className = 'event-time';
    time.textContent = localTime(record.received_at);
    row.append(mark, body, time);
    return row;
  });
  list.replaceChildren(...rows);
}

function render(state) {
  lastStateAt = Date.now();
  const broker = state.broker || {};
  const device = state.device || {};
  const telemetry = state.telemetry || {};
  const vitals = state.vitals || {};
  const gps = state.gps || {};
  const updatedAt = state.updated_at || {};
  const features = state.features || {};
  const hasTelemetry = Object.keys(telemetry).length > 0;
  const hasBrokerState = broker.message_count > 0 || Boolean(broker.error) || broker.connected === true;

  setBadge('device-badge', hasTelemetry ? Boolean(device.online) : null,
    '设备在线', '设备离线或数据超时', '设备状态未知');
  setBadge('broker-badge', hasBrokerState ? Boolean(broker.connected) : null,
    '公网链路正常', '公网链路断开', '公网服务连接中');
  setText('subtitle', `设备 ${state.device_id || '--'} · ${device.online ? '正在实时监护' : '显示云端最近状态'}`);

  const alarm = String(telemetry.alarm || 'UNKNOWN').toUpperCase();
  byId('alarm-card').className = `card alarm-card status-${alarm.toLowerCase()}`;
  setText('alarm', alarmNames[alarm] || '等待数据');
  setText('rssi', telemetry.rssi == null ? '--' : `${telemetry.rssi} dBm`);
  setText('uptime', duration(telemetry.uptime_ms));
  setText('updated', localTime(updatedAt.telemetry));

  setText('heart-rate', vitals.valid && vitals.heart_rate_bpm != null ? Math.round(vitals.heart_rate_bpm) : '--');
  setText('spo2', vitals.valid && vitals.spo2_pct != null ? Math.round(vitals.spo2_pct) : '--');
  const rawQuality = Number(vitals.signal_quality);
  const quality = Number.isFinite(rawQuality) ? Math.round((rawQuality <= 1 ? rawQuality * 100 : rawQuality)) : null;
  setText('quality', vitals.finger && quality != null ? `${Math.max(0, Math.min(100, quality))}%` : '--');
  setText('heart-note', vitals.online === false ? '传感器离线' : !vitals.finger ? '请完整覆盖传感器' : vitals.valid ? '测量有效' : '正在采集稳定信号');
  setText('spo2-note', vitals.valid ? '已获得有效测量' : '等待有效测量');
  setText('quality-note', vitals.finger ? 'PPG 实时质量' : '尚未检测到手指');

  const rhythmData = vitals.rhythm || {};
  const rhythm = String(rhythmData.state || 'DISABLED').toUpperCase();
  setText('rhythm', rhythmNames[rhythm] || rhythm);
  const rhythmCard = byId('rhythm-card');
  rhythmCard.className = `card metric rhythm-${rhythm.toLowerCase()}`;
  const confidence = rhythmData.valid && Number.isFinite(Number(rhythmData.confidence))
    ? ` · 置信度 ${Math.round(Number(rhythmData.confidence) * 100)}%` : '';
  setText('rhythm-note', `${rhythmData.model_calibrated ? '模型已标定' : '演示筛查，非医疗诊断'}${confidence}`);

  const sonarOnline = hasTelemetry ? optionalBoolean(telemetry, 'sonar_online') : null;
  const lightOnline = hasTelemetry ? optionalBoolean(telemetry, 'light_sensor_online') : null;
  const distanceCm = Number(telemetry.distance_cm);
  const lux = Number(telemetry.lux);
  const distanceValid = sonarOnline === true && telemetry.distance_cm != null &&
    Number.isFinite(distanceCm);
  const luxValid = lightOnline === true && telemetry.lux != null &&
    Number.isFinite(lux);
  setText('distance', distanceValid ? distanceCm.toFixed(1) : '--');
  setText('lux', luxValid ? Math.round(lux) : '--');
  setText('distance-note', sonarOnline === null ? '等待超声波数据'
    : distanceValid ? '超声波实时测距' : '传感器离线或暂无有效测距');
  setText('lux-note', lightOnline === null ? '等待光照传感器数据'
    : luxValid ? '环境照度实时值' : '传感器离线或暂无有效读数');

  const gpsOk = validCoordinate(gps);
  const gpsSource = gps.source === 'live' ? 'live' : gpsOk ? 'last' : 'none';
  byId('gps-dot').className = `dot ${gpsSource === 'live' ? 'ok' : gpsSource === 'last' ? 'last' : 'waiting'}`;
  setText('location-status', gpsSource === 'live' ? '已获得实时位置' : gpsSource === 'last' ? '显示最后有效位置' : '等待 GPS 定位');
  setText('lat', gpsOk ? Number(gps.lat).toFixed(6) : '--');
  setText('lon', gpsOk ? Number(gps.lon).toFixed(6) : '--');
  setText('satellites', gps.satellites == null ? 0 : gps.satellites);
  setText('gps-source', gpsSource === 'live' ? '实时' : gpsSource === 'last' ? '最后位置' : '无');

  setHealth('imu-health', hasTelemetry ? Boolean(telemetry.imu_online) : null);
  setHealth('max-health', hasTelemetry ? Boolean(telemetry.max30102_online) : null);
  setHealth('sonar-health', sonarOnline,
    { ok: '正常', fail: '离线/无数据', waiting: '等待' });
  setHealth('light-health', lightOnline,
    { ok: '正常', fail: '离线/无数据', waiting: '等待' });
  setHealth('gps-health', gpsSource === 'live' ? 'ok' : gpsSource === 'last' ? 'warn' : updatedAt.gps ? 'fail' : null,
    { ok: '已定位', warn: '最后位置', fail: '未定位' });
  setHealth('mqtt-health', hasBrokerState ? Boolean(broker.connected) : null,
    { ok: '已连接', fail: '已断开' });
  setText('message-count', broker.message_count == null ? 0 : broker.message_count);

  renderEvents(state.events);
  updateMap(gps, Boolean(features.amap_static_map));
}

async function loadState() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (_) {
    setBadge('broker-badge', false, '', '云端网页后端不可达', '');
  }
}

function connectStream() {
  const stream = new EventSource('/api/stream');
  stream.onmessage = event => {
    try { render(JSON.parse(event.data)); } catch (_) { /* 忽略单条损坏消息 */ }
  };
  stream.onerror = () => {
    setText('subtitle', '实时连接暂时中断，浏览器正在自动重连…');
  };
}

setInterval(() => {
  setText('clock', new Date().toLocaleString('zh-CN', { hour12: false }));
  if (Date.now() - lastStateAt > 20000) loadState();
}, 5000);

loadState();
connectStream();
