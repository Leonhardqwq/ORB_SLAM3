# Tracking 分阶段诊断：实现、实测与恢复位置

2026-10-19 本轮已完成。分支保持 `leonhardqwq`，没有暂存、提交或推送。承接上一批默认关闭的 workload 探针，继续应用第五步 / 有效耗时 E4；不是重做 B1–B3，也没有宣布 B6、E4–E6 全部通过。

研究结果与下一步统一见[论文侧报告](../../refer-papers/manuscripts/reliability-study/research/feedback-methods/follow-up/orb-slam3-tracking-stages-2026-10-19.md)，精简数据与完整命令见[实验入口](../../refer-papers/manuscripts/reliability-study/experiments/orb-slam3/results/tracking-stages-2026-10-19/README.md)。前一批[输入模式结果](input-mode-results-2026-10-19.md)保留。

## 实现

- `include/TrackingDiagnostics.h`、`src/TrackingDiagnostics.cc`：仅在固定所属线程的 T 调用中启用的线程局部计时作用域，八个互斥阶段；异常和提前返回由 RAII 收尾。默认关闭时不读取阶段时钟，仍有关闭分支调用成本。
- `System.h/.cc`：`SetFixedTrackingDiagnostics`、`FixedTrackingContext`、`FixedTrackingStages`，分别核对所属线程、启用和调用阶段。T 前读取当前活动地图数量、前帧关联计数与重置状态，不复制完整向量、不解引用退役地图点。
- `Frame.cc`、`Tracking.cc`：提取（含两个线程及 join）、匹配、初始化、初始位姿、局部更新/搜索/优化、关键帧决策等阶段。未归类的 T 时间单列，不能把这些计时当作纯 CPU 或完整内部归因。
- 回放及 `run_fixed_replay.py`：默认关闭的 `--tracking-diagnostics 0|1`；只允许固定 instrument 使用，输出 `replay-tracking.csv`。T 前快照在 W_T、结果读取在 W_B，时钟成本在 C_T，不扣除。
- `check_tracking_stages.py`、`test_tracking_stages.py`、`test_tracking_timer.cc`、`test_tracking_api.cc`、`verify_tracking_implementation.py`：边界与重叠、缺行/缺段、空白图像提前返回、关闭、错误阶段、非所属线程、固定和原生生命周期回归。
- `run_tracking_stage_campaign.py` 与[冻结协议](tracking-stage-protocol-2026-10-19.json)：相同新库上 off / workload / stages 三组，两序列各三次，1600 帧，块内随机、全部串行。

类布局有变化，使用 `build_isolated_replay.py` 在新目录重编主库及双目、单目、惯性双目、RGB-D 入口；没有用新头文件配旧库，没有打开全局 REGISTER_TIMES。视觉算法决策代码未作功能性替换，原生默认入口、内部双目并行、同步回环和完整 GBA 保留。

## 实际验收

18 次 / 28,800 帧全部完成，无无效位姿，预定 ATE 段真值覆盖均为 100%；阶段包含/无重叠、原有效耗时记账和关闭检查通过。计时器测试、真实空图返回、错误调用与固定/原生生命周期通过。真实构建运行仅在 WSL2 / Ubuntu 22.04，未声称所有传感器/道路或 Windows 原生/macOS 已验证。

提取占有效 T 约 42%–45%，双目匹配约 16%，其余未细分执行约 20%。V102 局部更新、搜索及双目匹配仍有较强历史预测信号；地图总规模没有稳定补齐条件，加入地图后历史仍使 T 检查误差下降约 36%–43%（V102）/17%–29%（V101）。旧八状态定义继续有解释力，但 E4 不接受，E5/E6 未进入。

墙钟中位数比均约 1；旧 workload 的 CPU 增加方向未重现，不能因此称探针加速。新 stages 在 V102 三对 ATE 都比 off 差，差值 +0.1054/+0.0435/+0.0366 m，且 stages 三次均超过旧 0.15 m 门槛。关键帧/回环/GBA 数量在重复间存在差异；CPU 比不是纯探针成本，不能宣布等效或因果。B6 的应用性能缺口保留。

新构建/原始采集位于 `/home/research/orb-tracking-stages-2026-10-19/`；新增普通文件长度约 1.36 GiB，排除链接复用的旧依赖/数据，不是实际分配空间。旧 6804 个图像及旧构建/共享依赖保护核验通过。原始日志与构建不进入 Git。

## 从这里继续

先定位同输入重复运行的首个实际工作分叉，并交叉核对 CPU 计量；源码中的指针键遍历和随机采样是待查线索，不能当已证实原因。再细分双目比较量、局部地图访问量和其余 T。当前轮内部计数先作解释量，不能直接用来定义当前可观测模式。

据机制决定是否做可选的稳定遍历/随机源控制、线程或缓冲复用，每项都保留原生默认并检查定位质量。不要仅凭提取占比大就改线程池，也不要仅凭地图增长就删地图或增加很多模式。随后才是少量模式冻结、新输入片段/场景和原三项条件的留出核验。积压、长 B 和低按时率仍为研究对象，不作为退回软件第一步的理由。
