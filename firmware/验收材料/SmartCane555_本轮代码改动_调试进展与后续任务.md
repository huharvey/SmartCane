# SmartCane555 本轮代码改动、调试进展与后续任务

> 基准版本：`SmartCane555.zip`  
> 当前依据：本轮 `验收材料.zip` + 已完成的实机调试记录  
> 目标：记录相对于 555 基准版已经做了什么、哪些已经可以结束，以及后续真正还需要做什么。

---

# 一、当前总体结论

相对于 `SmartCane555.zip`，本轮工作已经不是简单的“把新增模块接上”，而是完成了三类工作：

1. **跌倒检测从初始组合阈值方案发展成经过数据标定和独立验收的双路径检测方案；**
2. **MAX30102 从基础 HR/SpO₂ 原型链进一步完成了高频采集、峰值算法修正、IBI/HRV、SQI、节律窗口以及端侧推理性能验证；**
3. **公网 MQTT 固件与 Broker 链路已经过实机验证，并已把远程监护网页部署到阿里云 ECS。**

按当前课程项目/展示目标来看：

- **IMU 跌倒检测：已经完成，可停止继续调参；**
- **MAX30102 基础测量与信号处理：已经完成课程原型级调试；**
- **公网基础设施：ECS、Docker、Nginx、公网 IP 登录和演示数据页面已经完成；**
- **公网真实数据：历史记录已证明 ESP32 能通过 TLS 向 EMQX 发布数据，但仍需在拐杖在场时做一次“ESP32 → EMQX → ECS → 手机 4G/5G”的短程闭环复测并留图；**
- **目前唯一明显还未完成的核心算法开发，是把节律筛查的 baseline 权重替换为真正用有标签公开数据训练、验证得到的模型。**

标准血氧仪对照当前明确暂缓；网络也不按生产级系统继续做 LWT、8～24 h 长稳等深度可靠性验收。域名和 HTTPS 是推荐的安全升级，但不是本课程公网 IP 演示的硬性前置条件。

> 2026-09-02 部署更新：公网网页当前以 `SMARTCANE_DEMO=true` 运行，因此“公网服务器可访问”已经验收，“真实拐杖完整端到端数据”不能仅凭演示模式判定完成。

## 完成度复核表

| 模块/要求 | 状态 | 复核结论 |
|---|---|---|
| FreeRTOS 多任务与双核调度 | 已完成 | 传感器/决策/执行器与网络/遥测已分核运行 |
| 跌倒检测优化 | 已完成（课程原型） | 双路径检测、4 s 二次确认、取消冷却、独立样本验收均已留存 |
| 避障、SOS、照明和状态机 | 已完成 | 原有功能保留；当前 MAX30102 台架因 `0x57` 地址冲突暂时停用 I2C 超声波 |
| MAX30102 心率/血氧与 PPG 质量 | 已完成（课程原型） | 采样、峰值、IBI、HRV、SQI 和性能统计已验证；不宣称医疗精度 |
| TinyML 端侧推理链 | 基础链已完成 | 特征、量化、推理和状态机可运行 |
| 有标签异常节律训练模型 | 未完成 | 当前仍是 baseline 权重，`model_calibrated=false` |
| MQTT TLS 五类 Topic 发布 | 已完成 | presence、telemetry、vitals、gps、event 已实现并有 Broker/MQTTX 验收记录 |
| 独立公网前后端、SSE、只读页面 | 已完成 | 前端已拆分；浏览器不保存 MQTT 凭据；远程控制关闭；摄像头标注近场访问 |
| ECS Docker、Nginx、公网 IP 登录 | 已完成 | 演示模式健康检查和公网登录已通过 |
| 域名与 HTTPS | 未做、当前可选 | 公网 IP 演示不依赖域名；若长期真实使用则应补 HTTPS |
| 最终实机到手机移动网络闭环 | 未完成 | 等拐杖在场后关闭 Demo，做一次短回归并留证 |
| 公布源码前凭据清理 | 未完成 | 必须移除/轮换工程与服务器中的真实账号、密码和 Key |

---

# 二、相对于 SmartCane555.zip 的主要代码改动

## 1. 跌倒检测：从单一路径规则改为双路径状态机

主要修改文件：

```text
src/control/FallDetector.cpp
src/control/FallDetector.h
src/config/UserConfig.h
src/app/SmartCaneApp.cpp
src/services/SerialTelemetry.cpp/.h
```

### 1.1 FallDetector 算法结构修改

555 基准版主要逻辑为：

```text
低重力 / 冲击
→ 候选
→ 冲击已出现
→ 倾斜 + 低角速度保持
→ FALL candidate
```

本轮修改成两条并行确认路径：

```text
路径 A：严格路径
低重力/冲击
→ 必须观察到 impact
→ 大倾角 + 静止
→ 连续保持 600 ms
→ 检出

路径 B：深度失重路径
深度低重力 ≤ 0.40 g
→ 即使 10 Hz IMU 未采到冲击峰值
→ 大倾角 + 静止
→ 连续保持 1200 ms
→ 检出
```

主要新增：

- `deepFreeFallSeen_`；
- `StrictHolding / DeepHolding / BothHolding` 等候选阶段；
- strict/deep 两套独立保持计时；
- `Diagnostics` 调试结构；
- `phaseName()`；
- 加速度模长、角速度模长、倾角、free-fall、impact、tilted-and-still 等实时诊断量。

这次修改解决的核心问题是：**JY901S 实际约 10 Hz 时可能漏掉非常短的冲击峰值，因此不能把“必须采到 impact”作为所有跌倒的唯一入口。**

### 1.2 跌倒参数重新标定并冻结

555 初始值：

```text
FALL_FREE_FALL_G       = 0.55 g
FALL_IMPACT_G          = 2.20 g
FALL_TILT_DEG          = 55°
FALL_STILL_GYRO_DPS    = 35°/s
FALL_SEQUENCE_WINDOW   = 1500 ms
FALL_TILT_HOLD         = 800 ms
```

最终冻结为：

```text
FALL_FREE_FALL_G           = 0.55 g
FALL_DEEP_FREE_FALL_G      = 0.40 g
FALL_IMPACT_G              = 2.20 g
FALL_TILT_DEG              = 55°
FALL_STILL_GYRO_DPS        = 45°/s
FALL_SEQUENCE_WINDOW_MS    = 2000 ms
FALL_TILT_HOLD_MS          = 600 ms
FALL_DEEP_TILT_HOLD_MS     = 1200 ms
SUSPECTED_FALL_CONFIRM_MS  = 4000 ms
FALL_CANCEL_COOLDOWN_MS    = 3000 ms
```

同时增加 `static_assert` 对阈值和时间窗口关系进行编译期检查。

### 1.3 增加 IMU 高频调试数据链

新增串口命令：

```text
IMU STREAM ON
IMU STREAM OFF
```

新增独立 `imuDebugQueue_`，按 JY901S 新样本输出紧凑 CSV，而不是依赖普通 5 Hz JSON 遥测。

记录内容包括：

```text
ax ay az
gx gy gz
roll pitch yaw
A G Tilt
fall phase
free_fall
impact
tilted_still
alarm
suspected_fall
fall_latched
```

这样才能对阈值进行真实数据标定、离线重放和误报/漏报分析。

---

## 2. MAX30102：修正有效采样率并增强数据可观测性

主要修改文件：

```text
src/drivers/Max30102.cpp/.h
src/control/VitalsProcessor.cpp/.h
src/control/RhythmClassifier.cpp
src/model/SystemState.h
src/app/SmartCaneApp.cpp/.h
src/services/SerialTelemetry.cpp/.h
src/config/UserConfig.h
```

### 2.1 修正 FIFO 有效输出率的时间基准

MAX30102 仍使用：

```text
ADC sample rate = 100 Hz
FIFO averaging  = 4 samples
FIFO_CONFIG      = 0x5F
```

但本轮明确加入：

```cpp
FIFO_AVERAGE_SAMPLES = 4;
```

因此：

```text
有效 FIFO 输出率 = 100 / 4 = 25 Hz
实际样本周期 ≈ 40 ms
```

`SmartCaneApp.cpp` 不再按 100 Hz 给 FIFO 数据重建时间戳，而是按 **25 Hz** 处理。

这修复了之前最关键的时间轴问题：否则 IBI 会被压缩约 4 倍，HR 和节律特征都会失真。

同时增加：

- FIFO overflow 读取与记录；
- `lastOverflow()`；
- 采样序号、丢帧、最大间隔等上位机统计依据。

### 2.2 当前实物总线配置调整

当前实物调试配置中：

```text
MAX30102 → 主 I2C GPIO41/42
SONAR    → 暂时关闭
OLED     → 当前 bench 配置关闭
```

原因是 MAX30102 与原超声波模块地址均为：

```text
0x57
```

因此本轮代码增加：

```text
MAX30102_USE_PRIMARY_I2C
SONAR_ENABLED
OLED_ENABLED
```

以及 0x57 地址冲突的编译期保护。

这属于**当前实物接线条件下的 bench 配置**，不是最终硬件拓扑的永久结论。以后如果同时恢复 MAX30102 与 0x57 超声波，需要分离 I2C 总线或增加 I2C 多路复用器。

---

## 3. PPG / HR 算法：针对误峰、短 IBI 和陈旧 HR 做了重点修正

`VitalsProcessor.cpp` 是本轮 MAX30102 部分改动最大的文件。

555 基准版已经包含基础：

```text
去 DC
简单滤波
局部峰值检测
IBI
HR
SpO₂ 原型估算
SQI
HRV 特征
```

本轮在实测数据基础上增加了以下机制。

### 3.1 峰值突出度判据

峰值不再只看：

```text
局部极大值 + 幅度阈值
```

还必须满足相对前一谷值的 **prominence（突出度）**。

目标：减少一个真实心搏内部的小波峰被误认为第二个心搏，从而产生异常短 IBI。

### 3.2 自适应不应期

根据近期 IBI 的稳定情况设置有上限的不应期，抑制明显过早的二次峰。

但同时保留“突出度足够强的提前心搏”进入，避免为了去噪而把真实不规则心搏全部机械删掉。

### 3.3 HR 改用 IBI 中位数

显示 HR 从近期 IBI 均值改为：

```text
HR = 60000 / median(IBI)
```

提高对单个异常间隔的鲁棒性。

注意：**节律特征仍使用未被中位数平滑替代的有效 IBI 序列**，避免 HR 显示平滑反过来破坏节律分析。

### 3.4 长间隔重置旧 IBI 窗口

如果相邻峰之间出现过长间隔：

```text
旧 HR / IBI 连续窗口失效
→ 当前峰只作为新的时间锚点
→ 重新积累连续心搏
```

避免把“手指移开后又重新放上”等不连续数据拼成一个节律窗口。

### 3.5 心搏新鲜度保护

连续约 3 s 没有新的有效心搏时：

```text
旧 HR → NAN / invalid
```

而不是继续把几秒前的 HR 当作当前有效值显示。

这也是最终 P043 有效率下降但仍保留为有效验收样本的原因：系统选择安全失效，而不是输出陈旧数据。

### 3.6 增加 PPG 调试观测量

新增 `PpgProcessingDebug`：

```text
red_dc / ir_dc
red_ac / ir_ac
filtered_ir
envelope
peak_candidate
beat_accepted
ibi_ms
```

并增加：

```text
PPG STREAM ON
PPG STREAM OFF
```

配合独立 `ppgDebugQueue_` 输出 25 Hz CSV。

IMU 高频流与 PPG 高频流设置为互斥，避免串口带宽被同时占满。

---

## 4. 节律筛查：补充端侧性能观测，但模型本身仍是 baseline

当前模型结构仍为 6 维特征的轻量 INT8 线性分类器：

```text
IBI CV
RMSSD / mean IBI
pNN50
max adjacent IBI diff / mean
SQI
HR out-of-range score
```

输出：

```text
NORMAL
IRREGULAR
SUSPECTED_AF
```

本轮新增的主要代码不是“重新训练了模型”，而是增加工程观测量：

```text
inference_us
inference_count
model_bytes
classifier_state_bytes
```

同时把权重/偏置集中为明确的：

```text
MODEL_WEIGHTS
MODEL_BIAS
```

方便后续训练完成后直接替换。

当前仍保持：

```text
RHYTHM_MODEL_CALIBRATED = false
```

这一点必须保留，直到真正用 ECG 标签公开数据完成独立训练和测试。

---

## 5. Qt 上位机与离线分析工具：本轮新增了完整调试链

相对于 555 基准版，本轮围绕两个新任务补充了大量上位机/分析代码。

### IMU 部分

新增/扩展：

```text
串口协议解析
IMU 高频 CSV 采集
实时 IMU 曲线
场景与真实标签记录
trials.csv 汇总
跌倒状态机离线重放
参数网格扫描
自动测试
```

### MAX30102 部分

新增/扩展：

```text
PPG 25 Hz CSV 采集
RED/IR 与滤波波形
峰值标记
IBI
SQI
HR / SpO₂
节律状态
采样率 / 丢帧 / overflow 统计
自动测试
```

这些工具的价值不是最终产品功能，而是让“阈值和算法经过数据验证”能够留下完整证据。

---

## 6. MQTT：固件主体不是本轮新增，主要完成实机验收和远程展示

这里需要和其他两项区分开。

`SmartCane555.zip` 中已经存在：

```text
MqttRemoteService.cpp/.h
MQTT TLS
telemetry/vitals/gps/event
SOS/FALL 等事件接口
```

本轮验收包中的 `MqttRemoteService` 与 555 基准版主体没有实质性代码变化。

本轮真正完成的是：

- 配置并打通公网 MQTT Broker；
- MQTT over TLS / 8883 实机连接；
- 周期 telemetry / vitals / gps 接收；
- SOS QoS 1 事件实测；
- 新增只读远程监护网页；
- 网页显示设备状态、HR、SpO₂、GPS、SOS 等；
- 阿里云 ECS 上的 Docker 服务、Nginx 反向代理、公网 IP 登录和演示模式页面已经打通。

历史 MQTT 验收材料证明了设备可以把真实数据发到公网 Broker；本次 ECS 部署验收则证明了网页能从公网访问。但现有材料没有留下足够证据证明“最终固件真实数据已经从 ESP32 经过 EMQX 到达这台 ECS，并由手机 4G/5G 页面显示”。因此后续只需补一次短程闭环复测，不需要做生产级长稳或重复多轮深度网络测试。

---

# 三、本轮已经完成的调试与验收

## 1. IMU 跌倒检测：已完成

共完成四轮数据采集与调参。

最终冻结参数后的独立验收有效集：

```text
正常动作：12 次
误报：0 次

四方向模拟跌倒：4 次
检出：4 次

TP = 4
FN = 0
FP = 0
TN = 12
```

受控场景下：

```text
召回率 = 100%
误报率 = 0%
```

正常场景覆盖：

```text
静止直立
正常行走
快速行走
大幅摆杖
左转 / 右转
上台阶 / 下台阶
靠墙
正常放下
正常拿起
杖尖碰撞
```

跌倒覆盖：

```text
前 / 后 / 左 / 右
```

并完成：

```text
SUSPECTED_FALL
→ 约 4 s
→ FALL 锁存
```

前三轮 48 条数据和第 4 轮有效数据都进行了离线重放；最终分析工具中累计 64 条有效记录。

**结论：IMU 跌倒检测已经达到课程设计/工程原型交付标准。后续不建议继续调阈值。**

---

## 2. MAX30102 / PPG：基础链路和本地算法调试已完成

总计保存：

```text
43 份 PPG 原始记录
59098 个样本
总时长 2365.49 s ≈ 39.42 min
```

全部数据链：

```text
有效 FIFO 输出率 = 25 Hz
序号丢帧 = 0
FIFO overflow = 0
最大样本间隔 = 50 ms
```

覆盖场景包括：

```text
无手指
稳定覆盖
重复放置 / 移开
轻压 / 正常按压 / 重压
手指或模块运动
环境光变化
运动后恢复
节律稳定窗口
```

最终峰值算法修改后采集 P041～P043：

```text
有效 IBI = 243 个
IBI < 500 ms = 0
IBI > 1200 ms = 0
IBI CV = 0.070 / 0.058 / 0.100
```

说明之前最明显的短 IBI / 双峰问题已经解决。

当前能够完成：

```text
RED / IR 原始采集
去 DC
滤波
峰值检测
IBI
HR 趋势
SpO₂ 原型估算
SQI / valid 门控
15 s 节律窗口
端侧基线推理
```

**本阶段不做标准血氧仪对照。**

原因不是“已经证明 HR/SpO₂ 很准”，而是当前没有合适的可信参考仪器，因此课程项目只保留以下结论：

> 系统能够稳定获取 PPG、完成信号处理、输出 HR/SpO₂ 原型估算，并通过 SQI/valid 对低质量数据进行一定程度拒绝；不报告医疗级绝对精度。

当前 `SpO₂ = 110 - 25R` 仍属于课程原型近似。若课程要求仅为生命体征展示，可以保持现状；无需为了没有可靠 reference 的精度指标继续投入大量时间。

---

## 3. 节律端侧工程链：已完成，模型校准尚未完成

最终三组稳定数据共形成：

```text
29 次端侧推理
29 次 NORMAL
IRREGULAR = 0
SUSPECTED_AF = 0
```

推理性能：

```text
平均 ≈ 65.6 μs
P95   ≈ 95.4 μs
最大  ≈ 106 μs
```

说明：

```text
PPG
→ IBI/HRV 特征
→ 量化特征
→ 端侧分类器
→ 状态机
```

这条工程链已经工作正常，而且 ESP32-S3 的计算开销非常小。

但目前权重仍是 integration baseline，没有经过同步 ECG 标签训练，因此：

```text
model_calibrated = false
```

这是当前项目最主要的未完成项。

---

## 4. MQTT 公网链路：基础链路与公网网页已完成，真实整链待短回归

已经完成：

```text
MQTT over TLS / 8883
Broker 公网连接
周期 telemetry / vitals / gps
SOS QoS 1 事件
只读远程监护网页
阿里云 ECS Docker 健康检查
Nginx 反向代理
公网 IP 登录和演示数据页面
```

当前应准确表述为：

> 系统已实现基于 MQTT TLS 的设备公网遥测，并已把只读监护网页部署到阿里云 ECS；服务器公网访问已完成，最终还需在实机在场时进行一次手机移动网络端到端复测。

本次部署现状：

| 检查项 | 当前状态 | 说明 |
|---|---|---|
| Docker dashboard 服务 | 已完成 | 容器 healthy，后端只绑定 `127.0.0.1:8080` |
| `/livez`、`/readyz` | 已完成 | 演示模式返回 HTTP 200 |
| Nginx 80 端口反向代理 | 已完成 | ECS 本机通过 Nginx 访问返回 HTTP 200 |
| ECS 安全组与公网登录 | 已完成 | 实例关联安全组后，可通过公网 IP 登录 |
| MQTT 只读账号与五个精确 Topic ACL | 已配置 | 建议补一张允许订阅、拒绝越权的控制台或 MQTTX 截图 |
| 域名与 HTTPS | 暂缓/可选 | 公网 IP 课程演示可用；HTTP 登录口令未加密，不适合长期真实使用 |
| 真实拐杖数据进入 ECS 页面 | 待短回归 | 当前服务器为 `SMARTCANE_DEMO=true`，不能用模拟数据替代此项 |
| 手机关闭 Wi-Fi 后查看真实状态 | 待短回归 | 与上一项一次完成并截图留证 |

相关部署边界和验收步骤见 `remote_dashboard/公网IP部署验收记录.md`。

当前**不再要求**进一步完成：

```text
LWT offline 专项测试
Topic ACL 拒绝测试
8～24 h 长稳测试
生产级断网恢复时间评测
公网高可用性设计
```

这些属于产品化网络可靠性，不是当前展示需求的主要矛盾。但上表中的一次真实端到端短回归仍然需要完成。

---

# 四、后续真正还需要做的任务

## 任务 A：完成真正的异常节律模型训练【当前最重要】

类型：**电脑端代码 / 数据处理为主，硬件依赖很小。**

当前硬件端、特征端、部署接口都已经准备好，因此接下来不应继续修改 PPG 底层，而应直接进入模型训练。

建议保持现有 6 维特征接口：

```text
IBI CV
RMSSD / mean IBI
pNN50
max adjacent diff / mean IBI
SQI
HR out-of-range score
```

训练流程：

```text
带同步 ECG 标签的公开 PPG 数据
        ↓
实现与 ESP32 一致的峰值/IBI处理
        ↓
Python 与 ESP32 特征一致性检查
        ↓
按 15 s 窗口生成六维特征
        ↓
按受试者划分 train / val / test
        ↓
先训练逻辑回归/线性模型
必要时再比较小型 MLP
        ↓
独立测试集评估
        ↓
INT8 量化
        ↓
导出权重和偏置
        ↓
替换 RhythmClassifier.cpp
        ↓
RHYTHM_MODEL_CALIBRATED = true
```

最低应记录：

```text
受试者数
窗口数
混淆矩阵
precision
recall / sensitivity
specificity
F1
macro-F1 / balanced accuracy
INT8 前后性能
```

注意：本地 P001～P043 **不能作为 AF 真标签训练数据**，它们主要用于正常负样本、接触/运动伪影以及部署后的回归测试。

---

## 任务 B：训练模型替换后的短程回归测试

类型：**少量代码 + 少量实物测试。**

完成新模型后：

1. 替换 `RhythmClassifier.cpp` 中 baseline 的 `MODEL_WEIGHTS / MODEL_BIAS`；
2. 编译并烧录；
3. 确认模型字节数、RAM、Flash 和推理耗时没有异常；
4. 使用现有 P001～P043 做离线/软件回放，确认正常和伪影场景没有明显新增假报警；
5. 实物重新采 2～3 组 30～60 s 正常静止 PPG，确认端侧最终状态正常；
6. 通过后再把 `RHYTHM_MODEL_CALIBRATED` 置为 `true`。

这里不需要重新做 43 组完整 MAX30102 实验。

---

## 任务 C：最终整机回归与答辩演示

类型：**实物联调。**

不需要再做深度网络验收，但最终固件整体回归中必须顺带完成一次真实公网闭环。

建议最终完整演示链：

```text
系统开机
↓
IMU / GPS / MAX30102 等状态正常
↓
手指放置
↓
显示 HR / SpO₂ / PPG质量
↓
节律筛查给出正常状态
↓
远程网页正常收到公网数据
↓
触发 SOS 或受控模拟跌倒
↓
本地声光告警
+
远程页面 / MQTT 接收到事件
↓
解除报警
↓
恢复 NORMAL
```

这次回归时应关闭服务器演示模式，让 ESP32 使用设备账号连接 EMQX，让 ECS 使用独立只读账号订阅，再用关闭 Wi-Fi 的手机登录公网 IP。页面应显示真实运行时间、生命体征/GPS（无有效值时应如实显示）和一次 SOS 或跌倒事件。完成后保存 ESP32 串口、服务器日志和手机页面三处证据即可，不要求做多轮或长时间压力测试。

---

## 任务 D：整理最终报告材料

类型：**文档工作。**

建议最终报告至少保留四组结果：

### 跌倒检测

```text
最终阈值
双路径状态机
12 正常 + 4 跌倒独立验收混淆矩阵
离线重放结果
典型时域曲线
```

### MAX30102

```text
25 Hz 实际 FIFO 数据率
原始 PPG 与滤波 PPG
峰值 / IBI
修改前后短 IBI 对比
HR 运动后恢复趋势
SQI / valid 质量控制
```

### TinyML

```text
公开数据集
特征
训练/测试划分
混淆矩阵
Recall / F1
模型大小
ESP32 推理耗时
```

### 公网通信

```text
系统架构图
MQTT Topic
MQTTX / 远程网页截图
ECS 容器健康与 Nginx 反向代理结果
手机 4G/5G 显示真实设备数据的端到端截图
SOS / 告警远程展示
```

同时明确两个边界：

```text
1. HR/SpO₂ 为课程原型监测，不宣称医疗级测量精度；
2. 节律功能为异常筛查/疑似提示，不表述为房颤医学诊断。
```

---

# 五、当前不用继续做的事情

为了避免项目继续无边界扩展，下面这些当前可以明确停止或暂缓：

| 项目 | 当前处理 |
|---|---|
| IMU 再继续大规模采样调阈值 | 不需要，当前参数已冻结并独立验收 |
| 多轮跨网络/长时间压力测试 | 不需要；但需补一次最终实机到 ECS 手机页面的短闭环 |
| 标准血氧仪 HR/SpO₂ 精度对照 | 暂缓，不购买低质量 reference 为了凑指标 |
| LWT、ACL、8～24 h 网络长稳 | 不作为课程项目必做 |
| 医疗级 SpO₂ 标定 | 不做，当前只定位为课程原型估算 |
| 增加更多心律失常类别 | 暂不做，先完成当前 NORMAL / IRREGULAR / SUSPECTED_AF 范围 |
| LSTM / CNN / Transformer 节律模型 | 不需要，优先完成小型线性模型/MLP 的可靠训练 |
| 继续重构 ESP32 主工程 | 没有必要，当前架构已经足够稳定 |

---

# 六、推荐的最终收尾顺序

```text
当前状态
│
├─ IMU 跌倒检测 ─────────────── 已完成
│
├─ MAX30102 基础测量/信号处理 ─ 已完成
│
├─ MQTT / EMQX 固件链路 ─────── 已完成
│
├─ ECS 公网 IP 演示网页 ─────── 已完成
│
├─ 实机 → ECS → 手机短回归 ─── 待实机在场时完成
│
└─ 节律筛查
    ↓
    公开 ECG 标签 PPG 数据
    ↓
    Python 特征与训练
    ↓
    独立受试者测试
    ↓
    INT8 权重导出
    ↓
    替换 ESP32 baseline
    ↓
    少量本地回归
    ↓
    最终整机演示
    ↓
    报告整理
    ↓
    项目结束
```

因此，从现在开始，项目的主要矛盾已经不是硬件接线或 ESP32 主程序，而是：

> **把已经搭好的端侧异常节律筛查工程链，补上真正有标签的数据训练与验证，使 `model_calibrated=false` 能够有依据地变为 `true`。**

完成这一项以及最后一次包含真实公网闭环的整机回归后，本轮后续开发计划可以认为基本闭环。

此外，在公开仓库、提交课程压缩包或把工程交给他人前，应检查 `UserConfig.h` 和服务器 `.env`，删除真实 Wi-Fi、MQTT、地图和网页登录凭据，并对已经公开过的密码进行轮换。`.env` 不应进入版本库。
