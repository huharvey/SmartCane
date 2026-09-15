# SmartCane 远程守护网页

这是面向实际公网使用的只读仪表盘：后端通过 MQTT over TLS 订阅设备消息，浏览器通过 HTTPS/SSE 查看实时状态。MQTT 密码只存在服务器环境变量中，不会发送到浏览器；当前版本没有远程控制入口。

## 本机启动

```powershell
cd remote_dashboard
Copy-Item .env.example .env
```

编辑 `.env`，填写 MQTT 账号。建议在 EMQX 创建只能订阅 `smartcane/device01/#` 的只读账号，不要长期复用设备发布账号。

首次运行：

```powershell
.\run.ps1 -Install
.\run.ps1
```

浏览器打开 `http://127.0.0.1:8080`。不连接实际 Broker 的界面演示：

```powershell
.\run.ps1 -Demo
```

## 公网部署要求

1. 部署在持续运行的云服务器、容器平台或 NAS 上；事件 Topic 不保留，后端只有持续在线才能完整接收事件。
2. 设置 `WEB_HOST=0.0.0.0` 时，程序会强制要求 `DASHBOARD_USERNAME` 和 `DASHBOARD_PASSWORD`。
3. 使用 Caddy、Nginx 或平台自带网关提供 HTTPS，不要直接将 8080 明文端口暴露到公网。
4. MQTT 账号只允许订阅本设备 Topic，禁止发布和订阅 `command`。
5. `.env` 已被 `.gitignore` 排除，禁止提交密码。

Docker 示例：

```powershell
docker build -t smartcane-remote .
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env smartcane-remote
```

公网反向代理需要关闭响应缓冲，确保 `/api/stream` 的 SSE 实时推送不会被缓存。例如 Nginx 对该路径设置 `proxy_buffering off`。

## 页面状态判定

- `presence=online` 且 telemetry 15 秒内更新：设备在线。
- telemetry 超过 15 秒未更新：设备离线或链路异常。
- `event` 使用 QoS 1，显示 SOS、疑似跌倒、跌倒和节律筛查事件。
- GPS 无定位时显示等待，不会把 `null` 坐标误认为故障位置。

