/**
 * @file main.cpp
 * @brief OV2640 每 10 秒采集、缓存并通过 HTTP 发送 JPEG 的独立验证程序。
 *
 * 此文件只用于验证相机、PSRAM、Wi-Fi 和上位机接收链路；主工程图传实现
 * 位于 src/services/WifiCameraServer.*。
 */
#include <Arduino.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_heap_caps.h>
#include <esp_http_server.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <string.h>

#include "CameraPins.h"
#include "DemoConfig.h"

namespace {

struct CachedFrame {
  // data 指向堆中持久缓存，不是相机驱动临时帧缓冲。
  uint8_t *data = nullptr;
  size_t size = 0;
  uint32_t id = 0;
  uint32_t capturedAtMs = 0;
};

CachedFrame g_frame;
SemaphoreHandle_t g_frameMutex = nullptr;
httpd_handle_t g_server = nullptr;
uint32_t g_lastCaptureMs = 0;
bool g_apMode = false;

const char INDEX_HTML[] PROGMEM = R"HTML(
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32-CAM 10 秒图传</title><style>
body{font-family:system-ui;background:#0b1220;color:#e5edf9;margin:0;padding:20px}
.box{max-width:900px;margin:auto}.card{background:#172033;border:1px solid #2a3854;border-radius:16px;padding:16px}
img{display:block;width:100%;min-height:260px;object-fit:contain;background:#05070b;border-radius:12px}
.row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:12px}.muted{color:#9fb0c9}
button{background:#38bdf8;color:#052536;border:0;border-radius:9px;padding:10px 16px;font-weight:700}
</style></head><body><div class="box"><h1>ESP32-S3-CAM 定时图传</h1>
<div class="card"><img id="image" alt="camera"><div class="row"><span id="status" class="muted">等待首帧...</span>
<button onclick="refresh()">立即刷新</button></div></div></div><script>
async function refresh(){const started=performance.now();try{
 const response=await fetch('/capture?t='+Date.now(),{cache:'no-store'});
 if(!response.ok)throw new Error(await response.text());
 const blob=await response.blob();const old=image.src;image.src=URL.createObjectURL(blob);if(old.startsWith('blob:'))URL.revokeObjectURL(old);
 status.textContent='帧 '+(response.headers.get('X-Frame-Id')||'?')+' · '+blob.size+' 字节 · '+Math.round(performance.now()-started)+' ms';
 }catch(error){status.textContent='读取失败：'+error;}}
refresh();setInterval(refresh,10000);
</script></body></html>
)HTML";

String ipAddress() {
  return (g_apMode ? WiFi.softAPIP() : WiFi.localIP()).toString();
}

bool initCamera() {
  // 有 PSRAM 使用 VGA 双缓冲；无 PSRAM 自动降级，便于定位供电/配置问题。
  camera_config_t c{};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = CameraPins::D0;
  c.pin_d1 = CameraPins::D1;
  c.pin_d2 = CameraPins::D2;
  c.pin_d3 = CameraPins::D3;
  c.pin_d4 = CameraPins::D4;
  c.pin_d5 = CameraPins::D5;
  c.pin_d6 = CameraPins::D6;
  c.pin_d7 = CameraPins::D7;
  c.pin_xclk = CameraPins::XCLK;
  c.pin_pclk = CameraPins::PCLK;
  c.pin_vsync = CameraPins::VSYNC;
  c.pin_href = CameraPins::HREF;
  c.pin_sccb_sda = CameraPins::SIOD;
  c.pin_sccb_scl = CameraPins::SIOC;
  c.pin_pwdn = CameraPins::PWDN;
  c.pin_reset = CameraPins::RESET;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.grab_mode = CAMERA_GRAB_LATEST;

  if (psramFound()) {
    c.frame_size = FRAMESIZE_VGA;
    c.jpeg_quality = 12;
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 15;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
  }

  const esp_err_t result = esp_camera_init(&c);
  if (result != ESP_OK) {
    Serial.printf("[Camera] init failed: 0x%X\n", result);
    return false;
  }

  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor) {
    sensor->set_vflip(sensor, DemoConfig::CAMERA_VFLIP ? 1 : 0);
    sensor->set_hmirror(sensor, DemoConfig::CAMERA_HMIRROR ? 1 : 0);
  }
  Serial.printf("[Camera] ready, psram=%s\n", psramFound() ? "yes" : "no");
  return true;
}

bool captureFrame() {
  // 拷贝 JPEG 后立即归还相机帧缓冲，再用互斥量替换共享缓存。
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[Camera] capture failed");
    return false;
  }

  uint8_t *copy = static_cast<uint8_t *>(
      heap_caps_malloc(fb->len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!copy) {
    copy = static_cast<uint8_t *>(heap_caps_malloc(fb->len, MALLOC_CAP_8BIT));
  }
  if (!copy) {
    Serial.printf("[Camera] no memory for %u bytes\n", static_cast<unsigned>(fb->len));
    esp_camera_fb_return(fb);
    return false;
  }
  memcpy(copy, fb->buf, fb->len);
  const size_t size = fb->len;
  esp_camera_fb_return(fb);

  if (xSemaphoreTake(g_frameMutex, pdMS_TO_TICKS(2000)) != pdTRUE) {
    heap_caps_free(copy);
    return false;
  }
  if (g_frame.data) heap_caps_free(g_frame.data);
  g_frame.data = copy;
  g_frame.size = size;
  g_frame.id++;
  g_frame.capturedAtMs = millis();
  const uint32_t id = g_frame.id;
  xSemaphoreGive(g_frameMutex);

  Serial.printf("[Frame] id=%lu size=%u capturedAt=%lums\n",
                static_cast<unsigned long>(id), static_cast<unsigned>(size),
                static_cast<unsigned long>(millis()));
  return true;
}

esp_err_t rootHandler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

esp_err_t captureHandler(httpd_req_t *req) {
  // HTTP 线程只读取缓存，不直接触发相机，因此慢客户端不影响采集周期。
  if (!g_frameMutex || xSemaphoreTake(g_frameMutex, pdMS_TO_TICKS(2000)) != pdTRUE) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_sendstr(req, "frame busy");
  }
  if (!g_frame.data || g_frame.size == 0) {
    xSemaphoreGive(g_frameMutex);
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_sendstr(req, "no frame yet");
  }

  char value[24];
  snprintf(value, sizeof(value), "%lu", static_cast<unsigned long>(g_frame.id));
  httpd_resp_set_hdr(req, "X-Frame-Id", value);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(g_frame.capturedAtMs));
  httpd_resp_set_hdr(req, "X-Captured-At-Ms", value);
  httpd_resp_set_hdr(req, "Cache-Control", "no-store, no-cache, must-revalidate");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_type(req, "image/jpeg");
  const esp_err_t result = httpd_resp_send(
      req, reinterpret_cast<const char *>(g_frame.data), g_frame.size);
  xSemaphoreGive(g_frameMutex);
  return result;
}

esp_err_t statusHandler(httpd_req_t *req) {
  uint32_t id = 0;
  uint32_t capturedAtMs = 0;
  size_t size = 0;
  if (g_frameMutex && xSemaphoreTake(g_frameMutex, pdMS_TO_TICKS(250)) == pdTRUE) {
    id = g_frame.id;
    capturedAtMs = g_frame.capturedAtMs;
    size = g_frame.size;
    xSemaphoreGive(g_frameMutex);
  }
  String json;
  json.reserve(220);
  json += "{\"ok\":true,\"frame_id\":" + String(id);
  json += ",\"captured_at_ms\":" + String(capturedAtMs);
  json += ",\"size\":" + String(static_cast<unsigned>(size));
  json += ",\"interval_ms\":" + String(DemoConfig::CAPTURE_INTERVAL_MS);
  json += ",\"ap_mode\":" + String(g_apMode ? "true" : "false");
  json += ",\"ip\":\"" + ipAddress() + "\"}";
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(req, json.c_str(), json.length());
}

bool startServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.max_uri_handlers = 4;
  config.stack_size = 8192;
  if (httpd_start(&g_server, &config) != ESP_OK) return false;

  const httpd_uri_t routes[] = {
      {"/", HTTP_GET, rootHandler, nullptr},
      {"/capture", HTTP_GET, captureHandler, nullptr},
      {"/api/status", HTTP_GET, statusHandler, nullptr},
  };
  for (const auto &route : routes) {
    if (httpd_register_uri_handler(g_server, &route) != ESP_OK) return false;
  }
  return true;
}

bool startNetwork() {
  // 优先连接配置的路由器，超时或未配置时建立独立热点。
  WiFi.setSleep(false);
  if (DemoConfig::WIFI_SSID[0] != '\0') {
    WiFi.mode(WIFI_STA);
    Serial.println("[WiFi] connecting to configured hotspot...");
    WiFi.begin(DemoConfig::WIFI_SSID, DemoConfig::WIFI_PASSWORD);
    const uint32_t startedAt = millis();
    while (WiFi.status() != WL_CONNECTED &&
           millis() - startedAt < DemoConfig::WIFI_CONNECT_TIMEOUT_MS) {
      delay(250);
      Serial.print('.');
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
      g_apMode = false;
      Serial.printf("[WiFi] router connected: %s\n", ipAddress().c_str());
      return true;
    }
    Serial.println("[WiFi] hotspot connection failed; starting fallback AP");
    WiFi.disconnect(true);
  }

  WiFi.mode(WIFI_AP);
  g_apMode = true;
  if (!WiFi.softAP(DemoConfig::AP_SSID, DemoConfig::AP_PASSWORD)) return false;
  Serial.printf("[WiFi] AP %s, password %s, IP %s\n", DemoConfig::AP_SSID,
                DemoConfig::AP_PASSWORD, ipAddress().c_str());
  return true;
}

} // namespace

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[Demo] ESP32-S3-CAM 10-second snapshot server");

  g_frameMutex = xSemaphoreCreateMutex();
  if (!g_frameMutex) {
    Serial.println("[Demo] mutex creation failed");
    return;
  }
  if (!initCamera()) return;
  if (!startNetwork()) {
    Serial.println("[WiFi] start failed");
    return;
  }
  if (!captureFrame()) return;
  g_lastCaptureMs = millis();
  if (!startServer()) {
    Serial.println("[HTTP] start failed");
    return;
  }
  Serial.printf("[HTTP] open http://%s/\n", ipAddress().c_str());
}

void loop() {
  // 使用 millis() 定时，不用十秒 delay() 阻塞 HTTP 服务。
  const uint32_t nowMs = millis();
  if (g_frameMutex && nowMs - g_lastCaptureMs >= DemoConfig::CAPTURE_INTERVAL_MS) {
    g_lastCaptureMs = nowMs;
    captureFrame();
  }
  delay(20);
}
