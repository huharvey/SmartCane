# SmartCane 公网只读监护网页

该目录复用已经验证的 Python/MQTT 后端，将 ESP32 数据变成可通过公网查看的网站。当前课程演示采用“ECS 公网 IP + HTTP + Nginx”，域名与 HTTPS 作为后续安全升级；浏览器只连接 Python 后端，不会直接登录 MQTT。公网第一版没有 SOS、解除告警、灯光等远程控制入口。

## 目录

```text
remote_dashboard/
  frontend/
    index.html           # 从固件网页拆出的页面结构
    app.css              # 固件原有深色卡片配色与响应式布局
    app.js               # /api/status + /api/stream 数据刷新
  smartcane_remote/
    mqtt_bridge.py       # MQTT TLS，只订阅五个允许 Topic
    state.py             # 最新状态、最后有效 GPS、事件缓存
    amap.py              # 服务器端高德静态地图代理
  app.py                 # Flask API、SSE、网页登录保护
  compose.yaml           # 推荐的云服务器容器启动方式
  deploy/                # Nginx 与 systemd 示例
  DEPLOYMENT.md          # 从本机测试到手机 4G 验收的完整步骤
```

固件中的本地网页仍保留，用于 `192.168.4.1` 摄像头和近场调试；公网网页独立维护，不再把新的公网 HTML 塞回 ESP32 固件。

## 数据链路

```text
ESP32 -> MQTT TLS/8883 -> EMQX 公网 Broker
                              |
                       Python remote_dashboard
                              |
                  HTTP（当前）/HTTPS（可选）+ SSE
                              |
                       手机/电脑浏览器
```

后端只订阅：

- `smartcane/device01/presence`
- `smartcane/device01/telemetry`
- `smartcane/device01/vitals`
- `smartcane/device01/gps`
- `smartcane/device01/event`

## 本机演示

```powershell
cd remote_dashboard
Copy-Item .env.example .env
.\run.ps1 -Install
.\run.ps1 -Demo
```

浏览器打开 `http://127.0.0.1:8080`。演示模式不连接真实 Broker，会生成模拟心率、血氧、GPS 和事件。

连接真实 Broker 时，编辑 `.env`，把 `SMARTCANE_DEMO=false`，并填写 MQTT 只读账号。不要提交 `.env`；它已经被 `.gitignore` 与 `.dockerignore` 排除。

## HTTP 接口

- `GET /api/status`：兼容原固件网页使用习惯，返回 MQTT 缓存的云端状态。
- `GET /api/state`：与 `/api/status` 返回相同的规范化状态。
- `GET /api/stream`：SSE 实时状态流；15 秒无新消息时也会重算设备离线状态。
- `GET /api/map.png`：由服务器调用高德静态地图，不把地图 Key 发给浏览器。
- `GET /livez`：应用进程存活探针。
- `GET /readyz`：MQTT 是否已经连接的就绪探针。

没有 `/api/sos`、`/api/cancel` 或 `/api/light` 公网接口。

## 状态规则

- `presence=online`、telemetry 中 `online=true` 且 15 秒内更新：设备在线。
- telemetry 超过 15 秒：设备显示离线或数据超时。
- telemetry 同时显示超声波前方距离、BH1750 环境照度及两项传感器健康状态；数据无效或超过固件新鲜度期限时显示“离线/无数据”。
- GPS 失星或设备离线：继续显示后端保存的最后一次有效位置，并标成“最后位置”。
- NORMAL 为绿色；CAUTION/WARNING/DANGER 为黄色；疑似跌倒为橙色；SOS/FALL 为红色。
- 节律筛查是非医疗筛查；`model_calibrated=false` 时页面会明确显示“演示筛查，非医疗诊断”。
- 事件仅保存在进程内存中，服务重启后历史事件会清空；课程第一阶段可接受，长期使用应接数据库。

公网 IP 部署、登录账号、EMQX ACL、真实模式切换和手机 4G 验收见 [DEPLOYMENT.md](DEPLOYMENT.md)。本次实际部署状态见 [公网IP部署验收记录.md](公网IP部署验收记录.md)。

## 当前部署边界

- 已完成：ECS 上 Docker 容器健康运行、Nginx 80 端口反向代理、安全组关联、公网 IP 登录页访问。
- 当前模式：`SMARTCANE_DEMO=true`，页面数据由服务器模拟，并不代表实机已接入该网页。
- 待实机：将 `SMARTCANE_DEMO=false` 后，验证 ESP32 → EMQX → ECS → 4G/5G 浏览器的完整真实链路。
- 安全限制：HTTP Basic 登录在 HTTP 下不加密，只适合短期课程演示；真实健康和位置数据长期使用前应升级 HTTPS 或加密专网。
