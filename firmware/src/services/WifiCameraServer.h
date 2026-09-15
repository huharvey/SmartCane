#pragma once

/**
 * @file WifiCameraServer.h
 * @brief Wi-Fi 联网、OV2640 初始化、HTTP API 与 MJPEG 图传服务。
 *
 * 端口 80 提供状态/抓拍/命令，端口 81 专用于持续视频流，避免长连接阻塞
 * 普通 API。业务命令通过回调进入 SmartCaneApp，不在 HTTP 任务中直接执行。
 */

#include <Arduino.h>
#include <WiFi.h>
#include <esp_http_server.h>

class WifiCameraServer {
public:
  using JsonProvider = String (*)();
  using CommandHandler = bool (*)(const char *command, int value);

  // SSID 为空时直接建热点；否则先连路由器，超时后回退热点。
  void begin(JsonProvider jsonProvider, CommandHandler commandHandler);
  // 处理连接超时和断线回退，需由主循环周期调用。
  void update(uint32_t nowMs);
  bool networkReady() const { return state_ == State::Ready; }
  bool cameraReady() const { return cameraReady_; }
  bool apMode() const { return apMode_; }
  String ipAddress() const;
  int8_t rssi() const;
  void setIncidentActive(bool active) { incidentActive_ = active; }

private:
  enum class State : uint8_t { Stopped, Connecting, Ready }; // 仅描述网络服务状态
  void startAccessPoint();
  void startServices();
  bool initCamera();
  bool startHttpServers();

  static esp_err_t rootHandler(httpd_req_t *req);
  static esp_err_t statusHandler(httpd_req_t *req);
  static esp_err_t captureHandler(httpd_req_t *req);
  static esp_err_t streamHandler(httpd_req_t *req);
  static esp_err_t commandHandler(httpd_req_t *req);

  State state_ = State::Stopped;
  uint32_t connectStartedAtMs_ = 0;
  uint32_t disconnectedAtMs_ = 0;
  bool apMode_ = false;
  bool cameraReady_ = false;
  bool servicesStarted_ = false;
  volatile bool incidentActive_ = false;
  JsonProvider jsonProvider_ = nullptr;
  CommandHandler commandCallback_ = nullptr;
  httpd_handle_t webServer_ = nullptr;
  httpd_handle_t streamServer_ = nullptr;
  static WifiCameraServer *instance_;
};
