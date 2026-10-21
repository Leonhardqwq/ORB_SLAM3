# 固定模式实用性改进：冻结协议与运行入口

2026-10-17，在本批次新回放前冻结；机器可读参数见 [JSON](fixed-usability-protocol.json)。不覆盖首轮 400 帧失败记录。以下门槛用于判断是否值得继续研究，不是自动驾驶安全指标，也不是用户预先指定的行业标准。

## 本轮顺序和范围

1. 隔离核心库的进程级副作用，构建并运行原生兼容性检查；实现或回归失败时先修复，未解决则不进入对照。
2. 冻结首个用途：20 Hz 针孔双目、无闭环的局部定位与建图，面向能容忍局部漂移的上层集成试验。先检验短时定位能力，不承担完整导航、安全决策或长期全局一致性。
3. 比较原生同范围对照、固定普通睡眠、固定睡眠加 500 微秒主动检查。空闲及独立图像处理负载各三次，串行运行。每次从 EuRoC V1_01_easy 的第 800 个零基帧开始，初始化最多 100 帧，随后 800 帧评估，预加载上限 901 对图像。初始化成功前不计入评估；失败不能改起点重抽。三策略按重复号轮换运行顺序。
4. 完成本批比较并分别验收质量、资源和模型时序。模型对应未通过时停止模式拟合与可靠度预测；不能将实测截止成功率称为已获理论保证。

## 兼容性与配置

- 默认 `native_async` 和原传感器 API 保留。核心 `System` 不调用 OpenCV/Eigen 的进程级线程数设置。顺序提取左右图像由 `Execution.serialStereo` 控制，和全局线程池设置分开。
- `Execution.managedNoLoop: 1` 是研究用原生对照的显式选择，仅允许关闭 Viewer/闭环；直接登记重定位数据库并在退出时 join 工作线程。固定模式自动使用直接登记。默认原生 no-loop 分支恢复原本路径，不声称修复了上游关闭闭环时的所有问题。
- 退出不先等队列清空，避免 mapper 已被定位模式停止时无限等候。join 等当前工作单元结束；不承诺退出前处理所有未开始的关键帧。在线位姿是质量主证据，最终导出轨迹只作补充。
- 原生 GUI 退出还须先请求 Viewer 结束：由外部线程关闭时等待 Viewer，Viewer 菜单自身发起关闭时不自我 join。OpenCV/Pangolin 窗口由创建它们的 Viewer 线程销毁。本批初次原生单目惯性检查发现退出崩溃，原始库对照亦复现；两次失败与诊断保留在独立目录，不作为通过证据。
- 原生单目、双目惯性、单目惯性使用官方入口和原始配置做 1000 帧运行检查；RGB-D 和另一双目入口只作编译检查。无相关传感器数据不称实测通过。额外检查固定 API、两模式线程设置保持、原生定位模式切换/重置/停止后退出及非法配置拒绝。
- 原生功能保持分为源码、编译、运行、质量四层证据。`Frame` 等类改动没有保证二进制 ABI，宿主应用需重新编译。

## 判断标准

| 方面 | 本轮门槛与解释 |
|---|---|
| 定位质量 | 在线返回位姿做 SE(3) 刚体对齐，不拟合尺度；ATE RMSE ≤0.15 m；固定模式相对同负载原生中位值 ≤1.25 倍 +0.02 m；有效位姿和真值覆盖均 ≥99%；无评估期重置 |
| 实际时延 | 从计划释放计时，≤50 ms 成功，至少 99% 帧达标；评估吞吐 ≥19 Hz。该工程门槛不同于要求所有窗口满足原模型的门槛 |
| CPU/内存 | 评估期进程 CPU 时间 / 墙钟时间 ≤1 个逻辑核；固定模式相对原生中位值 ≤1.2 倍 +0.02 核；20 ms 采样的峰值 RSS ≤2 GiB，不称连续峰值上界 |
| 共用资源 | 独立单线程进程以 20 Hz 对同一真实图像做高斯滤波与 ORB 特征提取。对其完成时延的 p95，要求 ≤单独运行值的 1.2 倍 +0.2 ms；只在与评估期重叠部分统计。该负载是图像处理代理，不等同于实际感知网络或规划器 |
| 原模型对应 | 保留 H=20、原两节点图、原服务耗时定义及每个窗口累计误差 ≤100 微秒的既定协议；按论文原 `Model.step` 重算。未通过不能吸收唤醒/记录间隙进服务耗时，也不能放宽门槛 |

所有重复逐项验收；相对项使用同负载原生对照的三次中位数，不据结果改门槛。不把 800 帧或三次重复称为概率模型充分样本。EuRoC 是室内飞行器数据，支持软件定位组件的工程检查，不支持道路驾驶泛化结论。

## 可配置入口与复跑

核心库不决定宿主的线程策略。独立回放工具的 `--threads 1` 才会显式设置本次进程的 OpenCV、Eigen 和 OMP 等环境；默认 0 保持继承的政策。`--spin-us` 默认 0，上限 5000 微秒且不得超过周期的十分之一。没有默认绑核、实时优先级或系统级调整。

`tools/run_fixed_replay.py` 可指定 `--source --data --output --settings --timestamps --frames --offset --period-ns --init-limit --preload-limit --threads --spin-us`。当前加载器仍明确为 EuRoC 目录格式；这是有界预加载回放，不是相机实时队列。保持原始图像时间戳，调度释放原点固定，不按迟到重置。输入不足、容量不足或初始化失败即报错；不静默丢帧。

在 Linux/WSL 使用现有依赖创建新的源码快照并运行 `tools/build_fixed_stereo.sh` 后：

```bash
python3 tools/score_online_trajectory.py --selftest
python3 tools/run_usability_batch.py prepare --work "$ORB_WORK" --data "$EUROC_DATA" --protocol docs/fixed-usability-protocol.json
python3 tools/run_usability_batch.py compatibility --work "$ORB_WORK" --data "$EUROC_DATA" --protocol docs/fixed-usability-protocol.json
python3 tools/run_usability_batch.py comparison --work "$ORB_WORK" --data "$EUROC_DATA" --protocol docs/fixed-usability-protocol.json
```

`ORB_WORK` 为新的隔离工作目录，`EUROC_DATA` 为已有数据根；不写死机器路径进通用脚本。各运行拒绝覆盖已有目录，冻结输入哈希；源码变动需另开批次。原始日志、图像和构建在隔离工作区，精简检查结果另存本仓库 `docs/`。本机为 Windows + WSL2/Ubuntu 22.04，不能据此声明原生 Windows/macOS 编译或真实车辆验证。

同一隔离工作区的源码修订复测用 `--batch-name NEW_NAME` 另开记录，必须保留旧源码快照和失败批次。三个阶段传入同一个新名称；本次最终候选批次为 `usability-v3`。评分命令：

```bash
python3 tools/analyze_usability.py --work "$ORB_WORK" --data "$EUROC_DATA" \
  --protocol docs/fixed-usability-protocol.json --batch-name usability-v3 \
  --reference "$PAPER_ROOT/experiments/periodic-feedback/src/evaluate.py" \
  --output "$ORB_WORK/usability-v3/analysis.json"
```
