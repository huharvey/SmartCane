# 公网 IP 部署、调试与验收指南

本指南以本课程项目已经实际走通的方案为主：

```text
ECS 公网 IPv4 + Nginx/HTTP + Docker remote_dashboard
```

域名、DNS、Certbot 和 HTTPS 不再是本轮演示的前置条件，而是长期处理真实 GPS 与健康数据前的安全升级项。当前公网网页保持只读。

## 0. 2026-09-02 当前部署状态

已经完成：

- 阿里云 ECS 已运行 Docker Compose；
- `dashboard` 容器为 `healthy`；
- `127.0.0.1:8080/livez` 与 `/readyz` 在 Demo 模式返回 HTTP 200；
- Nginx 监听公网 80，并反向代理到 `127.0.0.1:8080`；
- ECS 实例已经加入放行 TCP 80 的安全组；
- 通过公网 IP 可以打开网页登录验证。

当前尚未完成：

- 当前为 `SMARTCANE_DEMO=true`，页面是服务器模拟数据；
- 实机不在现场，尚未验证 ESP32 → EMQX → ECS → 异地浏览器的最终完整链；
- 尚未留下手机关闭 Wi-Fi 后的 4G/5G 验收截图；
- 未购买域名，当前没有 HTTPS。

详细证据边界见 [公网IP部署验收记录.md](公网IP部署验收记录.md)。

## 1. 理解两种运行模式

### Demo 模式

```text
公网浏览器 → ECS/Nginx → remote_dashboard → DemoFeed 模拟数据
```

`.env` 设置：

```dotenv
SMARTCANE_DEMO=true
```

它不连接真实智能拐杖，也不要求实机在身边，适合部署和页面演示。

### 真实模式

```text
ESP32 → 可上网 Wi-Fi → EMQX Cloud → ECS remote_dashboard → 异地浏览器
```

`.env` 设置：

```dotenv
SMARTCANE_DEMO=false
```

ESP32 只连接 EMQX 分配的 Broker 主机名，不连接 ECS 的 80 端口，也不需要知道网页公网 IP。网页以后从公网 IP 换成域名时，不需要修改 ESP32 MQTT 固件。

## 2. 部署前准备

需要具备：

1. 一台有公网 IPv4 和公网带宽的 Linux ECS（Ubuntu 22.04/24.04）；
2. 当前 ECS 实例已加入正确的安全组；
3. 安全组入方向允许 TCP 80，不能把 8080 暴露到公网；
4. 服务器允许出站 TCP 8883（MQTT TLS）和 443（高德地图与软件更新）；
5. 真实模式需要 EMQX 独立网页只读账号；
6. 显示静态地图需要高德“Web 服务”Key。

当前网页登录使用 HTTP Basic Auth。它在普通 HTTP 下不能加密用户名和密码，因此公网 IP + HTTP 仅用于短期课程演示。必须使用独立临时密码，不能复用阿里云、邮箱、MQTT 或其他重要账号密码。

## 3. 创建 EMQX 网页只读账号

在 EMQX 控制台新建一个只给 Python 后端使用的账号，不要复用 ESP32 发布账号。

该账号只允许订阅：

```text
smartcane/device01/presence
smartcane/device01/telemetry
smartcane/device01/vitals
smartcane/device01/gps
smartcane/device01/event
```

ACL 要求：

- 允许 `subscribe` 上述五个精确 Topic；
- 禁止任何 `publish`；
- 禁止订阅 `smartcane/device01/command`；
- 不授予 `smartcane/#` 或 `#` 通配权限。

规则显示顺序不会改变匹配结果；需要关注的是权限动作、Topic 和是否存在更宽泛或冲突的规则。

## 4. Windows 本机 Demo（可选）

在 VS Code PowerShell 进入 `remote_dashboard`：

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Install
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Demo
```

浏览器打开 `http://127.0.0.1:8080`。这里是本机回环地址，不是公网地址。

## 5. ECS 配置 `.env`

在阿里云 Workbench 终端执行：

```bash
cd /opt/smartcane/remote_dashboard
cp .env.example .env
chmod 600 .env
nano .env
```

首次无实机演示使用：

```dotenv
MQTT_HOST=EMQX分配的公网主机名
MQTT_PORT=8883
MQTT_USERNAME=网页只读账号
MQTT_PASSWORD=网页只读账号密码
MQTT_DEVICE_ID=device01
MQTT_TOPIC_ROOT=smartcane
MQTT_CLIENT_ID=smartcane-web-device01
MQTT_CA_FILE=

AMAP_STATIC_MAP_KEY=高德Web服务Key

DASHBOARD_USERNAME=guardian
DASHBOARD_PASSWORD=独立临时强密码
DASHBOARD_AUTH_REQUIRED=true
SMARTCANE_DEMO=true
```

注意：

- `MQTT_HOST` 是 EMQX Cloud 分配的主机名，不是 ECS 公网 IP；
- `.env` 不上传到 Git，不放进截图；
- 修改 `.env` 后要重新创建容器才能可靠生效。

## 6. Docker Compose 启动与检查

```bash
cd /opt/smartcane/remote_dashboard
sudo docker compose up -d --build
sudo docker compose ps
```

检查后端：

```bash
curl -i http://127.0.0.1:8080/livez
curl -i http://127.0.0.1:8080/readyz
```

Demo 模式两个接口都应返回 HTTP 200 与：

```json
{"ok":true}
```

真实模式中：

- `/livez` 为 200：网页进程存活；
- `/readyz` 为 200：Python 后端已连接 EMQX；
- `/readyz` 为 503：MQTT 尚未连接，但不等于网页程序崩溃；
- `/readyz` 为 200 也不等于智能拐杖在线，设备在线还需要新鲜 telemetry。

查看日志：

```bash
sudo docker compose logs --tail=100 dashboard
```

## 7. 无域名 Nginx 公网入口

安装 Nginx：

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable --now nginx
```

复制本项目的公网 IP 模板：

```bash
cd /opt/smartcane/remote_dashboard
sudo cp deploy/nginx-smartcane.conf /etc/nginx/sites-available/smartcane
```

模板使用：

```nginx
listen 80 default_server;
listen [::]:80 default_server;
server_name _;
```

因此不需要把公网 IP 写死到源代码。禁用 Ubuntu 默认站点并启用本项目：

```bash
sudo unlink /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/smartcane /etc/nginx/sites-enabled/smartcane
sudo nginx -t
sudo systemctl reload nginx
```

`unlink` 提示文件不存在时可忽略。`nginx -t` 必须显示：

```text
syntax is ok
test is successful
```

不要把 Markdown 的三个反引号、`nginx`、`perl` 等代码块标记复制进配置文件。

检查代理：

```bash
curl -i http://127.0.0.1/livez
curl -i http://127.0.0.1/readyz
```

## 8. ECS 安全组

必须从“当前 ECS 实例详情 → 安全组”进入，确认安全组确实关联到该实例。仅仅创建安全组而未将实例加入，不会放通公网访问。

HTTP 演示规则：

| 项目 | 内容 |
|---|---|
| 方向 | 入方向 |
| 策略 | 允许 |
| 优先级 | 1 |
| IP 版本 | IPv4 |
| 协议 | TCP |
| 目的端口 | 80/80 |
| 来源 | `0.0.0.0/0`（需要异地任意网络访问时） |

保持以下边界：

- ECS 入方向不开放 8080；
- ECS 入方向不开放 8883，后端是主动出站连接 EMQX；
- SSH 22 尽量只允许管理者来源地址；
- HTTPS 尚未启用时，443 规则不会产生网页服务。

服务器检查：

```bash
sudo ss -lntp | grep -E ':80 |:8080 '
sudo ufw status verbose
```

正常应看到 Nginx 监听 `0.0.0.0:80`，Docker 仅监听 `127.0.0.1:8080`。ECS 从内部访问自己的公网 IP 可能因云网络回环而超时，应从外部电脑或手机验证。

## 9. 公网 IP 与手机验收

在 ECS 控制台实例详情复制“公网 IP”或已绑定的 EIP。不要使用 `10.*`、`172.16-31.*`、`192.168.*` 私网地址。

电脑浏览器明确输入：

```text
http://ECS_PUBLIC_IP
```

不要输入 `https://`。输入 `.env` 中的网页账号与密码。

手机验收：

1. 关闭手机 Wi-Fi，只保留 4G/5G；
2. 打开相同的 `http://ECS_PUBLIC_IP`；
3. 登录并确认页面能持续更新；
4. 保存一张能体现移动网络与页面内容的截图。

接口测试：

```powershell
curl.exe --max-time 15 -i http://ECS_PUBLIC_IP/livez
```

`/livez`、`/readyz` 是无需登录的运行探针。主页与 `/api/*` 数据接口需要登录。

## 10. 实机恢复后切换真实模式

```bash
cd /opt/smartcane/remote_dashboard
nano .env
```

修改：

```dotenv
SMARTCANE_DEMO=false
```

重新创建容器：

```bash
sudo docker compose up -d --force-recreate
sudo docker compose logs --tail=100 -f dashboard
```

看到后端 MQTT connected 后按 `Ctrl+C` 只会退出日志，不会停止容器。

实机最小验收：

1. ESP32 连接能够上网的路由器或手机热点；
2. 串口确认 MQTT connected；
3. 手机关闭 Wi-Fi，从公网 IP 登录；
4. 确认设备在线、HR/SpO₂/PPG/节律和 GPS 随实机数据变化；
5. GPS 失星后应显示最后有效位置；
6. 触发 SOS，确认本地声光和网页事件；再按实体按钮解除；
7. 按受控流程触发疑似跌倒与跌倒；
8. 断开 ESP32 网络，确认约 15 秒后网页显示离线，再验证恢复；
9. 保存串口、网页和 MQTT 日志。

公网网页没有远程控制；摄像头继续通过智能拐杖近场页面查看。

## 11. 可选升级：域名与 HTTPS

课程临时演示可以停留在公网 IP + HTTP。长期查看真实 GPS、健康数据时，建议完成：

1. 购买并实名认证域名；
2. 若服务器位于中国内地，先按阿里云要求确认并办理备案；
3. 添加 A 记录指向 ECS 公网 IP；
4. 将 Nginx 中两行 `default_server` 删除，并把 `server_name _;` 改为真实域名；
5. 安全组开放 TCP 443；
6. 安装 Certbot 并申请证书。

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx --redirect -d cane.example.com
sudo certbot renew --dry-run
```

域名方案完成后，最终只使用 `https://cane.example.com`。不要在证书验证前启用长期 HSTS。

## 12. 常见问题

### 公网超时

若 `127.0.0.1/livez` 为 200，而外部访问超时：

- 确认实例已加入所修改的安全组；
- 运行阿里云“安全组规则诊断”，检查 TCP 80；
- 确认公网 IP 与公网带宽有效；
- 检查网络 ACL；
- 关闭本地 VPN/代理后重试。

### HTTP 502

表示 Nginx 已收到请求，但无法连接后端：

```bash
sudo docker compose ps -a
curl -i http://127.0.0.1:8080/livez
sudo tail -n 50 /var/log/nginx/error.log
```

### HTTP 404

通常是请求落入 Ubuntu 默认站点。确认默认站点已禁用、本项目软链接已启用，并重新执行 `nginx -t` 与 reload。

### 页面显示设备离线

- 确认不是误把 Demo/真实模式理解反了；
- 检查后端 MQTT 日志；
- 检查五个精确 Topic ACL；
- 检查 ESP32 和后端 `MQTT_DEVICE_ID` 都为 `device01`；
- telemetry 超过 15 秒没有更新会自动显示离线。

### 高德地图不显示

- `.env` 必须填写高德“Web 服务”Key；
- 服务器必须能访问 `https://restapi.amap.com`；
- GPS 必须先提供有效坐标；
- 即使静态图失败，经纬度与详细位置链接仍可使用。

### 容器重启后事件列表清空

当前事件仅保存在内存中。课程阶段可以接受；需要长期追溯时再增加数据库。

## 13. 本阶段明确不做

- 不开放公网 SOS、取消告警和灯光控制；
- 不让浏览器直接连接 MQTT；
- 不把 MQTT 凭据写进前端 JavaScript；
- 不把 ESP32 MJPEG `:81/stream` 暴露到公网；
- 不通过 MQTT 传视频；
- 不把当前 HTTP 方案描述为可长期承载隐私数据的安全生产部署。
