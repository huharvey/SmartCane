# 智能拐杖异常节律候选模型训练

这套脚本把公开的 MIMIC PERform AF PPG 数据处理成与 ESP32 固件一致的 6 个轻量特征，按受试者划分训练、验证和独立测试集合，训练二分类逻辑回归，再量化为 ESP32 可直接使用的 INT8 参数。它还会回放已有 P001～P043 数据，检查正常和伪影场景是否出现新增严重假报警。

> 这是课程项目的风险筛查，不是医疗器械，也不能诊断房颤。最终提示必须使用“疑似异常节律/建议复测或就医”，不能写成“确诊房颤”。

## 需要的两个官方数据包

必须同时具备：

- `mimic_perform_af_csv.zip`：19 名房颤受试者；MD5 `df323c2be9db41589b5011ac9efb54ca`
- `mimic_perform_non_af_csv.zip`：16 名非房颤受试者；MD5 `84d5ad5e9fe94e83b40d6dbd36e4210e`

官方下载页：https://zenodo.org/records/6807403

只有 AF 包不能训练，因为模型必须同时看到“异常”和“正常”两类样本。脚本会在运行前校验两个文件的 MD5，防止断点下载留下损坏文件。

## Windows 操作

最省事的方法是不使用 PowerShell 脚本，直接在 CMD 或 VS Code 终端运行一键批处理（第二个参数是已有 P001～P043 数据目录）：

```bat
prepare_and_train.cmd "<local-path>\mimic_perform_af_csv.zip" "<local-path>\SmartCane_实机调试\SmartCane\验收材料\MAX30102与节律筛查验收\01-采集数据"
```

它会下载缺少的非房颤包、创建独立 Python 环境、安装依赖并执行训练。若下载中断，可再次运行；已经完整存在的包不会重复下载，训练脚本还会做 MD5 校验。

如果希望逐步操作，再使用下面的命令。

在 VS Code 的 PowerShell 终端中进入工程：

```powershell
Set-Location "<local-path>\SmartCane_实机调试\SmartCane\ml\rhythm"
py -3 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

然后运行（按实际下载位置修改两个 zip 路径）：

```powershell
python .\run_training.py `
  --af-zip "<local-path>\mimic_perform_af_csv.zip" `
  --non-af-zip "<local-path>\mimic_perform_non_af_csv.zip" `
  --local-captures "<local-path>\SmartCane_实机调试\SmartCane\验收材料\MAX30102与节律筛查验收\01-采集数据" `
  --output ".\artifacts\latest"
```

首次运行要解析数十段波形，耗时会明显长于后续运行。第二次默认复用 `public_features.csv`；需要重新提取时加 `--rebuild-features`。

## 输出文件怎么看

- `TRAINING_REPORT.md`：最先阅读的中文结论。
- `metrics.json`：完整测试指标、受试者划分和量化参数。
- `dataset_manifest.json`：数据包哈希、每个受试者可用窗口数。
- `public_test_predictions.csv`：只含从未参与训练/调参的测试受试者结果。
- `local_replay.csv` / `local_replay_summary.json`：P001～P043 软件回放结果。
- `RhythmModel.generated.h`：候选 INT8 参数；只有报告允许进入实物回归时才接入固件。
- `check_hardware_regression.py`：烧录后检查最后 2～3 组实物记录。
- `HARDWARE_REGRESSION_CHECKLIST.md`：拿到开发板后逐项照做的操作单。

## 为什么不能训练完就把 calibrated 改成 true

公开数据的传感器、佩戴位置和人群与本项目 MAX30102 不完全相同。即使公开测试达标，仍须：

1. 接入候选参数并编译烧录；
2. 检查模型字节数、RAM、Flash 和推理耗时；
3. 重新采 2～3 组 30～60 秒正常静止 PPG；
4. 确认端侧最终为 `NORMAL` 且没有新增严重假报警；
5. 最后才把 `RHYTHM_MODEL_CALIBRATED` 设为 `true`。

脚本不会自动修改这个开关。
