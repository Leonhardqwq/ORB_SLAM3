# 本 fork 的研究计划

## 当前入口与并行路线（2026-10-21）

固定调度路线继续在 `leonhardqwq` 保存已有实现和证据。最新独立检查见 [Machine Hall 结果](machine-hall-results-2026-10-19.md)：50 ms 主截止下的预测误差满足预定 10 个百分点要求，但 Tracking 历史影响与部分真值覆盖未通过，不能判为模型适用性全部验收通过。后续 [特征预算机制检查](extraction-budget-results-2026-10-19.md)未支持扩大该候选的 SLAM 实验。

并行的原生时延路线拟从固定上游版本建立独立 `research/native-timing` 分支和 `../ORB_SLAM3-native/` 工作树，先在自动驾驶相关输入上测量实际时延与定位表现，再评估可靠性问题；不要求原生程序先适配现有理论。当前本地上游基点为 `4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4`，不是联网确认的最新版本。

两条路线使用各自的源码快照、构建和运行输出目录，原始数据共享只读。建立新工作树、采集原生道路数据均为下一阶段工作；本次仅保存当前进度，不改变历史失败结论。

## 历史起点与专题导航

本仓库在用户的 `leonhardqwq` 分支上，探索将 ORB-SLAM3 的任务调度适配到已有固定图可靠性模型。

- [多场景实用性检查与优化约束](fixed-schedule-usability-review-2026-10-17.md)：用户新增核心要求；当前证据不足，唤醒优化须可选并核查共享资源影响。
- [六步应用与验收总计划](../../refer-papers/manuscripts/reliability-study/research/feedback-methods/follow-up/orb-slam3-six-step-plan.md)：建图、测量、采集、模式/联合分布及可靠度预测。
- [固定模式实现、试运行及停止位置](fixed-schedule-progress-2026-10-17.md)、[机器可读验收](fixed-schedule-verification-2026-10-17.json)、[测量契约](fixed-measurement.md)。
- [软件改造 B1—B6](fixed-schedule-plan.md)与[B1 源码/接口设计](fixed-schedule-design.md)。
- [WSL2 + Ubuntu 计划及预算](wsl-ubuntu-plan.md)、[实际进度与续接](wsl-ubuntu-setup.md)、[核验 JSON](wsl-ubuntu-verification.json)。
- [2026-10-16 原生 Windows 配置记录](fixed-schedule-progress-2026-10-16.md)，保留历史失败证据。
- [仓库约定](../AGENTS.md)。

2026-10-17 已从环境搭建推进到真实软件改造：B2/B3 通过，三次插桩及三次无插桩各完成 400 帧。固定模式保持单线程并执行真实建图。模型时序还原的最大偏差为 161—184 微秒，超过事先规定的 100 微秒，故停止在应用步骤 4 / B4—B5 的时序验收；未进入概率拟合、可靠度预测或定位质量比较。原生基线和此前环境证据保留；复现及恢复入口见本轮记录。

跨仓库链接按 ORB_SLAM3 与 refer-papers 同级布局编写，仅用于阅读，不是构建依赖。
