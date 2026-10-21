# 图像任务模式与工作量观测改造

2026-10-19 已完成本轮。当前分支 `leonhardqwq` 保持，未暂存/提交/推送。承接 B4/B5 观测完善、应用第五步和有效耗时 E4；不是重新开始 B1，也不是宣布 B6 或 E4—E6 全部通过。

用户补充的“模式来自图像任务与软件/资源共同作用”已落实为实际检查。完整研究结论、数据和后续任务统一放在[论文侧记录](../../refer-papers/manuscripts/reliability-study/research/feedback-methods/follow-up/orb-slam3-input-modes-2026-10-19.md)，[精简实验入口](../../refer-papers/manuscripts/reliability-study/experiments/orb-slam3/results/input-modes-2026-10-19/README.md)保存结果与重跑命令。

## 软件变化

- `tools/extract_input_features.cc`：离线从当前双目及上一张左图提取七个输入特征，不使用未来图像或耗时标签。已有 OpenCV 4.5.4，零新依赖；线上接入成本尚未测量。
- `Examples/Stereo/stereo_fixed_replay.cc`、`tools/run_fixed_replay.py`：增加默认关闭的 `--workload-diagnostics 0|1`，仅固定 instrument 运行支持。记录前/后跟踪点、关联数量、CPU 和协调线程切换；只计指针是否非空，不解引用地图点；不改变视觉算法。
- `tools/build_input_mode_replay.py`：按 v3 增量 build.json 重编独立回放，旧库、词典和依赖只读复用。初次误用 Ninja 入口失败的目录保留，新入口构建通过，兼容既有 C++11。
- `tools/check_input_workload.py`、`test_input_workload.py`：检查探针确实落在就绪后间隙、没有漏行和非法计数。成本留在有效耗时，不扣除。
- `tools/run_input_mode_campaign.py`、`verify_input_mode_campaign.py`：[冻结协议](input-mode-campaign-protocol-2026-10-19.json)下串行配对回放、独立分析/生命周期回归。

主库 src/include 未改，原生默认行为保留；回环、GBA、双目内部并行、真实建图和跨轮反馈均保留。默认关闭和原生/固定生命周期已实测；不以此代替所有传感器或道路部署验证。

## 实测验收

两序列各三对探针开/关，每次 1600 帧，共 12 次 / 19,200 帧。全部完成且无无效位姿，事件边界、探针包含及整数纳秒递推通过。墙钟中位数比分别 1.00097、0.99996，满足 1.05 门槛；CPU 比 1.08974、1.28702，不称为无扰动。V102 三对开启端 ATE 都高于关闭端，实用性差异保留，不能由仅三对作强因果结论。每个探针中位数约 7–12 微秒，其耗时包含在 T/B 有效服务中。

四个图像模式在新 V102/V101 完整段上改善 T 对数均方误差约 14%–22% / 2%–7%，但后段迁移均更差。加入实际 T 前工作量有额外解释力；8 状态有限组合在 V102/V101 的额外改善约 21% / 8%–15%，仍有历史信号和稀少模式。候选方向保留，E4 尚未接受，E5/E6 未进入。固定视频重复不是随机场景过程的独立样本，高模式保持率不证明马尔可夫性。

实际构建与采集：WSL2 / Ubuntu 22.04。分析/探针单元检查也在 Windows 通过；macOS 与 Windows 原生 SLAM 未新验证。输出在 `/home/research/orb-input-modes-2026-10-19/`，新增普通文件长度约 11.33 MiB，排除链接复用的既有资源。旧 6804 个图像文件哈希及 62 项构建基线保护核验通过。

## 下一步

从 E4 的 8 状态候选与 V102 剩余历史继续，补可选的 T 内阶段计时和开始前地图规模，区分提取、匹配、局部查询/优化与资源因素。已有 getter 不能代表全地图规模。先定位原因再决定是否调整内存分配、线程复用或工作组织；目前没有这些机制的因果结论。进一步核对 CPU/定位探针差异，再用新片段/场景验证冻结候选。

模式诊断不足时继续本步诊断；测量错误修测量，样本不足补采。应用性能单列，积压和长任务保留。不能删尾部、丢慢帧、删除回环/GBA、给每帧独立模式或偷偷改理论来过关。
