/**
 * @file WifiCameraServer.cpp
 * @brief ESP32-S3-CAM 热点/路由器模式、网页、抓拍和 MJPEG 实现。
 */
#include "WifiCameraServer.h"
#include "../config/BoardConfig.h"
#include "../config/UserConfig.h"
#include <esp_camera.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <string.h>

WifiCameraServer *WifiCameraServer::instance_ = nullptr;

namespace {
// 固件内置的轻量调试网页；正式上位机位于 upper_computer/。
// HTML numeric entities retain Chinese labels without depending on a Windows
// source-file encoding.  Explicit DOM lookups also work on mobile browsers.
const char INDEX_HTML[] PROGMEM = R"HTML(
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>&#26234;&#33021;&#25296;&#26454;</title><style>
body{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:16px}
.wrap{max-width:900px;margin:auto}.card{background:#1e293b;border-radius:14px;padding:14px;margin:12px 0}
img{width:100%;border-radius:10px;background:#000;min-height:220px;object-fit:contain}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.v{font-size:1.5rem;font-weight:700}button{border:0;border-radius:9px;padding:12px;margin:5px;background:#38bdf8;color:#082f49;font-weight:700}
.danger{background:#fb7185;color:#4c0519}.muted{color:#94a3b8}.status-normal{color:#4ade80}.status-caution,.status-warning,.status-danger,.status-irregular{color:#facc15}.status-suspected_fall{color:#fb923c}.status-sos,.status-fall,.status-suspected_af{color:#fb7185}.selected{outline:3px solid #e2e8f0}.static-map{width:100%;height:280px;border:0;border-radius:10px;background:#0b1220;display:block;object-fit:cover}.map-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}.map-link{color:#7dd3fc}
</style></head><body><div class="wrap"><h1>&#26234;&#33021;&#25296;&#26454;&#30417;&#25511;</h1>
<div class="card"><img id="cam" alt="camera stream"></div>
<div class="grid"><div class="card">&#29366;&#24577;<div class="v" id="alarm">--</div></div>
<div class="card">&#36317;&#31163;<div class="v"><span id="distance">--</span> cm</div></div>
<div class="card">&#20809;&#29031;<div class="v"><span id="lux">--</span> lx</div></div>
<div class="card">GPS<div class="v" id="gps">--</div></div>
<div class="card">&#24515;&#29575;<div class="v"><span id="heart-rate">--</span> bpm</div></div>
<div class="card">&#34880;&#27687;<div class="v"><span id="spo2">--</span> %</div></div>
<div class="card">PPG<div class="v" id="vitals-state">--</div></div>
<div class="card">&#33410;&#24459;&#31579;&#26597;<div class="v" id="rhythm-state">--</div><div class="muted" id="rhythm-detail">&#38750;&#35786;&#26029;</div></div>
<div class="card">&#20844;&#32593; MQTT<div class="v" id="mqtt-state">--</div><div class="muted" id="mqtt-detail">--</div></div></div>
<div class="card"><div id="detail" class="muted">&#27491;&#22312;&#35835;&#21462;...</div>
<button class="danger" id="sos">SOS &#27714;&#21161;</button><button id="cancel">&#35299;&#38500;&#21578;&#35686;</button>
<button id="light-on">&#24320;&#28783;</button><button id="light-off">&#20851;&#28783;</button><button id="light-auto">&#33258;&#21160;&#29031;&#26126;</button></div>
<div class="card"><div class="v">&#20301;&#32622;&#22320;&#22270;</div><div id="map-note" class="muted">&#31561;&#24453; GPS &#23450;&#20301;...</div><img id="amap-static-map" class="static-map" alt="&#39640;&#24503;&#20301;&#32622;&#22320;&#22270;" hidden><div class="map-actions"><a id="map-amap" class="map-link" target="_blank" rel="noopener" hidden>&#22312;&#39640;&#24503;&#22320;&#22270;&#20013;&#25171;&#24320;</a></div></div>
</div><script>
const cam=document.getElementById('cam'),alarmEl=document.getElementById('alarm');
const distanceEl=document.getElementById('distance'),luxEl=document.getElementById('lux');
const gpsEl=document.getElementById('gps'),detailEl=document.getElementById('detail');
const heartRateEl=document.getElementById('heart-rate'),spo2El=document.getElementById('spo2'),vitalsStateEl=document.getElementById('vitals-state'),rhythmStateEl=document.getElementById('rhythm-state'),rhythmDetailEl=document.getElementById('rhythm-detail'),mqttStateEl=document.getElementById('mqtt-state'),mqttDetailEl=document.getElementById('mqtt-detail');
const mapNoteEl=document.getElementById('map-note'),amapLink=document.getElementById('map-amap'),amapMap=document.getElementById('amap-static-map');
const lightButtons=[document.getElementById('light-auto'),document.getElementById('light-off'),document.getElementById('light-on')];
const alarmNames={NORMAL:'&#27491;&#24120;',CAUTION:'&#25552;&#37266;',WARNING:'&#35686;&#21578;',DANGER:'&#21361;&#38505;',SUSPECTED_FALL:'&#30097;&#20284;&#36300;&#20498;',FALL:'&#36300;&#20498;&#25253;&#35686;',SOS:'SOS &#27714;&#21161;'};
cam.src=location.protocol+'//'+location.hostname+':81/stream';
cam.onerror=()=>{detailEl.innerHTML='&#35270;&#39057;&#27969;&#26080;&#27861;&#36830;&#25509;';};
function lightModeName(mode){return mode===1?'&#25163;&#21160;&#24320;':mode===0?'&#25163;&#21160;&#20851;':'&#33258;&#21160;';}
function setAlarmStyle(alarm){alarmEl.className='v status-'+String(alarm||'NORMAL').toLowerCase();}
function setLightButtons(mode){lightButtons.forEach((b,i)=>b.classList.toggle('selected',i===mode+1));}
function gpsStatus(gps,lastFix){return gps.valid?'&#24050;&#23450;&#20301;':(lastFix.available?'&#20449;&#21495;&#20013;&#26029;':(gps.utc!=='--:--:--'||gps.satellites>0?'&#25628;&#32034;&#21355;&#26143;':'&#26410;&#23450;&#20301;'));}
function gpsDetail(gps,lastFix){const point=gps.valid?gps:(lastFix.available?lastFix:null);if(!point)return `GPS&#21355;&#26143; ${gps.satellites}`;const source=gps.valid?'GPS&#23454;&#26102;&#23450;&#20301;':'GPS&#26368;&#21518;&#26377;&#25928;&#20301;&#32622;';return `${source} | &#32428;&#24230; ${point.lat.toFixed(6)} | &#32463;&#24230; ${point.lon.toFixed(6)} | &#21355;&#26143; ${point.satellites}`;}
function updateVitals(v){const x=v||{online:false};heartRateEl.textContent=x.valid&&x.heart_rate_bpm!=null?Number(x.heart_rate_bpm).toFixed(0):'--';spo2El.textContent=x.valid&&x.spo2_pct!=null?Number(x.spo2_pct).toFixed(0):'--';if(!x.online){vitalsStateEl.textContent='&#27169;&#22359;&#31163;&#32447;';vitalsStateEl.className='v muted';return;}if(!x.finger){vitalsStateEl.textContent='&#35831;&#25918;&#32622;&#25163;&#25351;';vitalsStateEl.className='v muted';return;}if(!x.valid){vitalsStateEl.textContent='&#20449;&#21495;&#37319;&#38598;';vitalsStateEl.className='v muted';return;}vitalsStateEl.textContent=`${Math.round(Number(x.signal_quality||0)*100)}%`;vitalsStateEl.className='v status-normal';}
function updateRhythm(v){const r=(v&&v.rhythm)||{};const names={DISABLED:'&#24050;&#20851;&#38381;',NO_SENSOR:'&#27169;&#22359;&#31163;&#32447;',NO_FINGER:'&#35831;&#25918;&#32622;&#25163;&#25351;',COLLECTING:'&#37319;&#38598;&#20013;',MOTION_ARTIFACT:'&#35831;&#20445;&#25345;&#38745;&#27490;',INCONCLUSIVE:'&#20449;&#21495;&#19981;&#36275;',NORMAL:'&#33410;&#24459;&#35268;&#21017;',IRREGULAR:'&#33410;&#24459;&#19981;&#35268;&#21017;',SUSPECTED_AF:'&#30097;&#20284;&#24322;&#24120;&#33410;&#24459;'};const state=r.state||'DISABLED';rhythmStateEl.innerHTML=names[state]||state;rhythmStateEl.className='v '+(state==='NORMAL'?'status-normal':state==='IRREGULAR'?'status-irregular':state==='SUSPECTED_AF'?'status-suspected_af':'muted');if(!r.model_available){rhythmDetailEl.innerHTML='&#27169;&#22411;&#26410;&#21551;&#29992;&#65307;&#38750;&#35786;&#26029;';return;}const base=r.model_calibrated?'&#24050;&#26631;&#23450;&#27169;&#22411;':'&#28436;&#31034;&#22522;&#32447;&#65288;&#38750;&#35786;&#26029;&#65289;';const detail=r.valid?`${base} | &#32610;&#20449;&#24230; ${Math.round(Number(r.confidence||0)*100)}% | IBI ${r.beat_count||0} &#27425;`:base;rhythmDetailEl.innerHTML=detail;}
function updateMqtt(m){const x=m||{enabled:false,state:'DISABLED'};const names={DISABLED:'&#26410;&#21551;&#29992;',CONFIG_ERROR:'&#37197;&#32622;&#38169;&#35823;',WAIT_WIFI:'&#31561;&#24453;&#32852;&#32593;',WAIT_TIME:'TLS &#26657;&#26102;&#20013;',CONNECTING:'&#36830;&#25509;&#20013;',ONLINE:'&#24050;&#36830;&#25509;',ERROR:'&#36830;&#25509;&#38169;&#35823;'};const state=x.state||'DISABLED';mqttStateEl.innerHTML=names[state]||state;mqttStateEl.className='v '+(state==='ONLINE'?'status-normal':state==='CONFIG_ERROR'||state==='ERROR'?'status-suspected_af':'muted');mqttDetailEl.innerHTML=x.enabled?(x.connected?'&#20844;&#32593;&#36965;&#27979;&#24050;&#21551;&#29992;':'&#35831;&#26816;&#26597; Wi-Fi&#12289;&#36134;&#21495;&#21644; TLS &#35777;&#20070;'):'&#22312; UserConfig.h &#37197;&#32622;&#21518;&#21551;&#29992;';}
const AMAP_STATIC_KEY='__AMAP_STATIC_MAP_KEY__';
let shownStaticMapKey='';
function outsideChina(lat,lon){return lon<72.004||lon>137.8347||lat<0.8293||lat>55.8271;}
function transformLat(x,y){return -100+2*x+3*y+.2*y*y+.1*x*y+.2*Math.sqrt(Math.abs(x))+(20*Math.sin(6*x*Math.PI)+20*Math.sin(2*x*Math.PI))*2/3+(20*Math.sin(y*Math.PI)+40*Math.sin(y/3*Math.PI))*2/3+(160*Math.sin(y/12*Math.PI)+320*Math.sin(y*Math.PI/30))*2/3;}
function transformLon(x,y){return 300+x+2*y+.1*x*x+.1*x*y+.1*Math.sqrt(Math.abs(x))+(20*Math.sin(6*x*Math.PI)+20*Math.sin(2*x*Math.PI))*2/3+(20*Math.sin(x*Math.PI)+40*Math.sin(x/3*Math.PI))*2/3+(150*Math.sin(x/12*Math.PI)+300*Math.sin(x/30*Math.PI))*2/3;}
function wgs84ToGcj02(lat,lon){if(outsideChina(lat,lon))return {lat,lon};const a=6378245,ee=.00669342162296594323,rad=lat*Math.PI/180;let dLat=transformLat(lon-105,lat-35),dLon=transformLon(lon-105,lat-35),magic=1-ee*Math.sin(rad)*Math.sin(rad),sqrtMagic=Math.sqrt(magic);dLat=dLat*180/((a*(1-ee)/(magic*sqrtMagic))*Math.PI);dLon=dLon*180/(a/sqrtMagic*Math.cos(rad)*Math.PI);return {lat:lat+dLat,lon:lon+dLon};}
function updateStaticMap(point,isLive){if(!AMAP_STATIC_KEY){amapMap.hidden=true;mapNoteEl.innerHTML='&#26410;&#37197;&#32622;&#39640;&#24503;&#22320;&#22270; Key';return;}const converted=wgs84ToGcj02(Number(point.lat),Number(point.lon)),mapLat=Math.round(converted.lat*1000)/1000,mapLon=Math.round(converted.lon*1000)/1000,color=isLive?'0x008000':'0xFFFF00',mapKey=`${isLive?'live':'last'}:${mapLat.toFixed(3)},${mapLon.toFixed(3)}`;if(mapKey===shownStaticMapKey&&!amapMap.hidden)return;shownStaticMapKey=mapKey;amapMap.src=`https://restapi.amap.com/v3/staticmap?location=${mapLon.toFixed(3)},${mapLat.toFixed(3)}&zoom=16&size=900*360&markers=mid,${color},:${mapLon.toFixed(3)},${mapLat.toFixed(3)}&key=${encodeURIComponent(AMAP_STATIC_KEY)}`;amapMap.hidden=false;}
amapMap.onerror=()=>{mapNoteEl.innerHTML='&#39640;&#24503;&#22320;&#22270;&#21152;&#36733;&#22833;&#36133;&#65307;&#35831;&#26816;&#26597;&#25163;&#26426;&#32593;&#32476;&#19982; Key &#37197;&#32622;';};
function updateMap(gps,lastFix){const point=gps.valid?gps:(lastFix.available?lastFix:null);const isLive=gps.valid;if(!point){shownStaticMapKey='';amapMap.hidden=true;mapNoteEl.innerHTML='&#31561;&#24453; GPS &#23450;&#20301;&#65307;&#23450;&#20301;&#25104;&#21151;&#21518;&#23558;&#26174;&#31034;&#26368;&#21518;&#26377;&#25928;&#20301;&#32622;';amapLink.hidden=true;return;}updateStaticMap(point,isLive);mapNoteEl.innerHTML=isLive?'&#23454;&#26102;&#23450;&#20301;&#65307;&#32511;&#33394;&#26631;&#35760;&#20026;&#24403;&#21069;&#20301;&#32622;&#65288;&#22270;&#22320;&#22266;&#23450;&#65292;&#19981;&#21487;&#32553;&#25918;&#65289;':'&#20449;&#21495;&#20013;&#26029;&#65307;&#40644;&#33394;&#26631;&#35760;&#20026;&#26368;&#21518;&#19968;&#27425;&#26377;&#25928;&#23450;&#20301;';const lat=Number(point.lat),lon=Number(point.lon);amapLink.href=`https://uri.amap.com/marker?position=${lon.toFixed(6)},${lat.toFixed(6)}&name=SmartCane&coordinate=wgs84&callnative=0`;amapLink.hidden=false;}
async function refresh(){try{const s=await (await fetch('/api/status',{cache:'no-store'})).json();
alarmEl.innerHTML=alarmNames[s.alarm]||s.alarm;setAlarmStyle(s.alarm);distanceEl.textContent=s.distance_cm??'--';luxEl.textContent=s.lux??'--';
const lastFix=s.last_fix||{available:false};gpsEl.innerHTML=gpsStatus(s.gps,lastFix);setLightButtons(s.light_mode);updateVitals(s.vitals);updateRhythm(s.vitals);updateMqtt(s.mqtt);updateMap(s.gps,lastFix);
detailEl.innerHTML=`IP ${s.ip} | ${gpsDetail(s.gps,lastFix)} | IMU ${s.imu.valid?'&#27491;&#24120;':'&#31163;&#32447;'} | &#29031;&#26126; ${s.light?'&#24050;&#24320;':'&#24050;&#20851;'} (${lightModeName(s.light_mode)})`;
}catch(e){detailEl.innerHTML='&#35774;&#22791;&#36830;&#25509;&#20013;&#26029;';}}
async function command(url,method='GET'){try{const r=await fetch(url,{method,cache:'no-store'});if(!r.ok)throw new Error(r.status);detailEl.innerHTML='&#21629;&#20196;&#24050;&#21457;&#36865;&#65292;&#31561;&#24453;&#35774;&#22791;&#24212;&#29992;...';setTimeout(refresh,180);}catch(e){detailEl.innerHTML='&#21629;&#20196;&#22833;&#36133;&#65292;&#35831;&#26816;&#26597;&#35774;&#22791;&#36830;&#25509;';}}
document.getElementById('sos').onclick=()=>command('/api/sos','POST');
document.getElementById('cancel').onclick=()=>command('/api/cancel','POST');
document.getElementById('light-on').onclick=()=>command('/api/light?mode=on');
document.getElementById('light-off').onclick=()=>command('/api/light?mode=off');
document.getElementById('light-auto').onclick=()=>command('/api/light?mode=auto');
setInterval(refresh,1000);refresh();</script></body></html>
)HTML";

constexpr char STREAM_TYPE[] = "multipart/x-mixed-replace;boundary=frame";
constexpr char STREAM_BOUNDARY[] = "\r\n--frame\r\n";
constexpr char STREAM_PART[] = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";
}

void WifiCameraServer::begin(JsonProvider jsonProvider, CommandHandler commandHandler) {
  // 保存回调后启动非阻塞联网流程；关闭 Wi-Fi 休眠以提高视频流稳定性。
  instance_ = this;
  jsonProvider_ = jsonProvider;
  commandCallback_ = commandHandler;
  WiFi.setSleep(false);

  if (Config::WIFI_SSID[0] == '\0') {
    startAccessPoint();
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(Config::WIFI_SSID, Config::WIFI_PASSWORD);
  connectStartedAtMs_ = millis();
  state_ = State::Connecting;
}

void WifiCameraServer::update(uint32_t nowMs) {
  // 连接路由器失败或运行中长时间掉线时，自动切换为独立热点。
  if (state_ == State::Connecting) {
    if (WiFi.status() == WL_CONNECTED) {
      state_ = State::Ready;
      apMode_ = false;
      startServices();
    } else if (nowMs - connectStartedAtMs_ >= Config::WIFI_CONNECT_TIMEOUT_MS) {
      startAccessPoint();
    }
  } else if (state_ == State::Ready && !apMode_) {
    if (WiFi.status() == WL_CONNECTED) {
      disconnectedAtMs_ = 0;
    } else {
      if (disconnectedAtMs_ == 0) disconnectedAtMs_ = nowMs;
      if (nowMs - disconnectedAtMs_ >= Config::WIFI_CONNECT_TIMEOUT_MS)
        startAccessPoint();
    }
  }
}

void WifiCameraServer::startAccessPoint() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_AP);
  apMode_ = true;
  state_ = WiFi.softAP(Config::AP_SSID, Config::AP_PASSWORD) ? State::Ready
                                                             : State::Stopped;
  if (state_ != State::Ready) return;
  startServices();
}

void WifiCameraServer::startServices() {
  // 相机和 HTTP 服务器只初始化一次，切换网络模式时复用现有服务。
  if (servicesStarted_) return;
  cameraReady_ = initCamera();
  servicesStarted_ = startHttpServers();
}

String WifiCameraServer::ipAddress() const {
  if (!networkReady()) return "0.0.0.0";
  return (apMode_ ? WiFi.softAPIP() : WiFi.localIP()).toString();
}

int8_t WifiCameraServer::rssi() const {
  return apMode_ || WiFi.status() != WL_CONNECTED ? 0 : static_cast<int8_t>(WiFi.RSSI());
}

bool WifiCameraServer::initCamera() {
  // 引脚来自 BoardConfig；有 PSRAM 时采用 VGA 双缓冲，否则降级为 QVGA。
  camera_config_t c{};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Board::CAM_PIN_D0;
  c.pin_d1 = Board::CAM_PIN_D1;
  c.pin_d2 = Board::CAM_PIN_D2;
  c.pin_d3 = Board::CAM_PIN_D3;
  c.pin_d4 = Board::CAM_PIN_D4;
  c.pin_d5 = Board::CAM_PIN_D5;
  c.pin_d6 = Board::CAM_PIN_D6;
  c.pin_d7 = Board::CAM_PIN_D7;
  c.pin_xclk = Board::CAM_PIN_XCLK;
  c.pin_pclk = Board::CAM_PIN_PCLK;
  c.pin_vsync = Board::CAM_PIN_VSYNC;
  c.pin_href = Board::CAM_PIN_HREF;
  c.pin_sccb_sda = Board::CAM_PIN_SIOD;
  c.pin_sccb_scl = Board::CAM_PIN_SIOC;
  c.pin_pwdn = Board::CAM_PIN_PWDN;
  c.pin_reset = Board::CAM_PIN_RESET;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.grab_mode = CAMERA_GRAB_LATEST;

  const bool hasPsram = psramFound();
  Serial.printf("[Camera] PSRAM=%s size=%u free_heap=%u\n",
                hasPsram ? "yes" : "no", ESP.getPsramSize(), ESP.getFreeHeap());
  if (hasPsram) {
    // Start with one QVGA buffer.  It is substantially more stable on a
    // battery-powered S3-CAM than VGA double buffering and is enough for the
    // required 5-10 fps demonstration stream.
    c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 12;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 20;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
  }

  const esp_err_t cameraError = esp_camera_init(&c);
  if (cameraError != ESP_OK) {
    Serial.printf("[Camera] init failed: 0x%X\n", static_cast<unsigned>(cameraError));
    return false;
  }
  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor) {
    sensor->set_vflip(sensor, Config::CAMERA_VFLIP ? 1 : 0);
    sensor->set_hmirror(sensor, Config::CAMERA_HMIRROR ? 1 : 0);
  }
  return true;
}

bool WifiCameraServer::startHttpServers() {
  // 普通 API 与持续 MJPEG 分开端口，避免视频长连接占用控制通道。
  httpd_config_t webConfig = HTTPD_DEFAULT_CONFIG();
  webConfig.max_uri_handlers = 8;
  webConfig.stack_size = 8192;
  if (httpd_start(&webServer_, &webConfig) != ESP_OK) return false;

  const httpd_uri_t routes[] = {
    {"/", HTTP_GET, rootHandler, nullptr},
    {"/api/status", HTTP_GET, statusHandler, nullptr},
    {"/capture", HTTP_GET, captureHandler, nullptr},
    {"/api/sos", HTTP_POST, commandHandler, nullptr},
    {"/api/cancel", HTTP_POST, commandHandler, nullptr},
    {"/api/light", HTTP_GET, commandHandler, nullptr}
  };
  for (const auto &route : routes) httpd_register_uri_handler(webServer_, &route);

  if (!cameraReady_) return true;
  httpd_config_t streamConfig = HTTPD_DEFAULT_CONFIG();
  streamConfig.server_port = 81;
  streamConfig.ctrl_port = webConfig.ctrl_port + 1;
  streamConfig.stack_size = 8192;
  if (httpd_start(&streamServer_, &streamConfig) != ESP_OK) return false;
  const httpd_uri_t streamUri = {"/stream", HTTP_GET, streamHandler, nullptr};
  httpd_register_uri_handler(streamServer_, &streamUri);
  return true;
}

esp_err_t WifiCameraServer::rootHandler(httpd_req_t *req) {
  String page(INDEX_HTML);
  page.replace("__AMAP_STATIC_MAP_KEY__", Config::AMAP_STATIC_MAP_KEY);
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, page.c_str(), page.length());
}

esp_err_t WifiCameraServer::statusHandler(httpd_req_t *req) {
  String json = instance_ && instance_->jsonProvider_ ?
                instance_->jsonProvider_() : String("{\"error\":\"no provider\"}");
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(req, json.c_str(), json.length());
}

esp_err_t WifiCameraServer::captureHandler(httpd_req_t *req) {
  // 帧缓冲使用完必须归还相机驱动，否则很快耗尽缓冲区。
  if (!instance_ || !instance_->cameraReady_) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_sendstr(req, "camera unavailable");
  }
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.printf("[Camera] frame failed: psram=%u free_heap=%u\n",
                  ESP.getFreePsram(), ESP.getFreeHeap());
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "capture failed");
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  const esp_err_t result = httpd_resp_send(req, reinterpret_cast<const char *>(fb->buf), fb->len);
  esp_camera_fb_return(fb);
  return result;
}

esp_err_t WifiCameraServer::streamHandler(httpd_req_t *req) {
  // multipart 每个分片包含边界、JPEG 类型和长度，客户端断开即退出循环。
  httpd_resp_set_type(req, STREAM_TYPE);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  char header[64];
  while (true) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) return ESP_FAIL;
    const size_t headerLength = snprintf(header, sizeof(header), STREAM_PART, fb->len);
    esp_err_t result = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (result == ESP_OK) result = httpd_resp_send_chunk(req, header, headerLength);
    if (result == ESP_OK) result = httpd_resp_send_chunk(
        req, reinterpret_cast<const char *>(fb->buf), fb->len);
    esp_camera_fb_return(fb);
    if (result != ESP_OK) return result;
    const uint32_t interval = instance_->incidentActive_
        ? Config::CAMERA_INCIDENT_FRAME_INTERVAL_MS
        : Config::CAMERA_NORMAL_FRAME_INTERVAL_MS;
    if (interval) vTaskDelay(pdMS_TO_TICKS(interval));
  }
}

esp_err_t WifiCameraServer::commandHandler(httpd_req_t *req) {
  // HTTP 回调只翻译命令并入队，不直接操作告警/照明对象。
  if (!instance_ || !instance_->commandCallback_)
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no command handler");

  bool accepted = true;
  if (strcmp(req->uri, "/api/sos") == 0) {
    accepted = instance_->commandCallback_("sos", 1);
  } else if (strcmp(req->uri, "/api/cancel") == 0) {
    accepted = instance_->commandCallback_("cancel", 1);
  // req->uri includes the query string, e.g. "/api/light?mode=on".  Match
  // only the path prefix so light commands actually reach the control queue.
  } else if (strncmp(req->uri, "/api/light", strlen("/api/light")) == 0 &&
             (req->uri[strlen("/api/light")] == '\0' ||
              req->uri[strlen("/api/light")] == '?')) {
    char query[48]{};
    char mode[12]{};
    int value = -1;
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK &&
        httpd_query_key_value(query, "mode", mode, sizeof(mode)) == ESP_OK) {
      if (strcmp(mode, "on") == 0) value = 1;
      else if (strcmp(mode, "off") == 0) value = 0;
    }
    accepted = instance_->commandCallback_("light", value);
    Serial.printf("[HTTP] light mode=%s value=%d %s\n", mode, value,
                  accepted ? "queued" : "queue-full");
  }
  // HTTPD_503_SERVICE_UNAVAILABLE is not exposed by every Arduino-ESP32
  // bundled ESP-IDF version.  Use the portable response APIs instead.
  if (!accepted) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_sendstr(req, "command queue full");
  }
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, "{\"ok\":true}");
}
