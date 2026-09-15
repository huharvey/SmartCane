# SmartCane 公网 IP 部署验收记录

记录日期：2026-09-02

## 当前结论

远程监护网页已经部署到阿里云 ECS，并可通过“公网 IPv4 + Nginx + HTTP”进入网页登录页。域名、DNS 与 Certbot 不再作为本轮课程演示的阻塞项。

本次验证的是云端网页基础设施和 Demo 数据链，不应写成“真实智能拐杖已经完成端到端公网验收”。实机当前不在现场，完整真实链路仍需在设备恢复后补一次短程回归。

## 已核对证据

| 检查项 | 结果 | 证据/说明 |
|---|---|---|
| Docker Compose | 通过 | `dashboard` 容器为 `healthy` |
| 后端存活 | 通过 | `127.0.0.1:8080/livez` 返回 HTTP 200 与 `{"ok":true}` |
| Demo 就绪 | 通过 | `127.0.0.1:8080/readyz` 返回 HTTP 200 |
| Nginx 反向代理 | 通过 | `127.0.0.1/livez` 返回 HTTP 200 |
| 端口边界 | 通过 | Nginx 监听 `0.0.0.0:80`；Docker 仅绑定 `127.0.0.1:8080` |
| Ubuntu UFW | 通过 | 状态为 inactive，未拦截 80 |
| ECS 安全组 | 通过 | 当前实例已关联允许 TCP 80 的安全组；关联后公网访问恢复 |
| 公网登录页 | 通过 | 公网 IP 页面可打开并显示登录验证 |
| 域名/HTTPS | 有意延期 | 当前未购买域名，使用 HTTP 公网 IP；只适合短期演示 |
| 实机真实数据 | 待验证 | 当前 `SMARTCANE_DEMO=true`，数据由服务器模拟 |
| 手机 4G/5G | 待留证 | 应关闭 Wi-Fi 后保存一次公网访问截图 |

## 本轮源码验证

- 远程后端自动测试：20 项全部通过（含 Docker 回环端口与 Nginx/SSE 部署边界测试）。
- 前端 `app.js`：Node.js 语法检查通过。
- ESP32 主工程：PlatformIO `esp32-s3-cam` release 编译通过；RAM 使用 55,308 B（16.9%），Flash 使用 1,012,877 B（51.5%）。

公网 IP 与域名都没有被硬编码到前端或 ESP32 固件中。浏览器继续使用同源相对接口，ESP32 继续连接 EMQX Broker，因此以后更换 ECS IP 或升级域名时不需要重写业务代码。

## 当前访问链

```text
电脑/手机浏览器
    ↓ HTTP（公网 IP）
阿里云 ECS Nginx :80
    ↓
127.0.0.1:8080 remote_dashboard
    ↓
DemoFeed（当前模拟数据）
```

实机恢复后的目标链路：

```text
ESP32（可上网的 Wi-Fi/热点）
    ↓ MQTT TLS/8883
EMQX Cloud
    ↓ MQTT TLS/8883
ECS remote_dashboard
    ↓ Nginx + 公网 IP
异地亲属浏览器
```

ESP32 不连接 ECS 的 80 端口，也不需要知道网页公网 IP；它仍然连接 EMQX 分配的 Broker 主机名。网页使用公网 IP 或以后改用域名，都不需要改 ESP32 MQTT 固件。

## 实机回来后的最小验收

1. 在服务器 `.env` 中设置 `SMARTCANE_DEMO=false`，保留真实 MQTT 只读账号。
2. 执行 `sudo docker compose up -d --force-recreate`。
3. 确认 `/livez` 为 200；`/readyz` 为 200 只表示后端已连接 Broker。
4. ESP32 接入可上网的 Wi-Fi，串口确认 MQTT connected。
5. 手机关闭 Wi-Fi，通过公网 IP 登录，确认设备在线且数据随实机变化。
6. 验证 GPS、生命体征、SOS、疑似跌倒/跌倒事件与设备离线/恢复。
7. 保存网页、串口与 MQTT 日志作为最终端到端证据。

## 安全边界

- 当前 HTTP Basic 登录在 HTTP 下不加密；必须使用独立临时密码，不得复用阿里云、邮箱或 MQTT 密码。
- 公网只开放 80；8080 不开放，MQTT 8883 是服务器主动出站连接，也不开放为 ECS 入站端口。
- 公网网页保持只读，不提供 SOS、取消告警和灯光远程控制。
- 摄像头继续使用近场页面，不向公网暴露 ESP32 的 81 端口。
- 若长期展示真实 GPS/生命体征，应升级为域名 + HTTPS，或使用仅授权家庭成员加入的加密专网。
