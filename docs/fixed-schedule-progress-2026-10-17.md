# 固定调度实现、真实回放与停止位置

> 后续实用性批次（2026-10-17）：已隔离线程政策和研究对照行为，修复原生 Viewer 退出，并完成扩大后的兼容回归及 18 次质量/资源/时序对照。固定模式仍有原模型时序验收失败；停止概率拟合与预测。 见[最新结果](fixed-usability-results-2026-10-17.md)。下文保留此前检查或首轮实验的历史口径。

2026-10-17。工作在 `leonhardqwq` 分支，基线提交 `4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4`；本轮源码修改尚未提交。**固定顺序模式已经实现并运行；采集检查通过，模型时序还原未通过。依照总计划停止在应用步骤 4，不进行模式拟合、可靠度预测或 B6。**

机器可读证据：[核验 JSON](fixed-schedule-verification-2026-10-17.json)。前置环境和完整原生回放仍以 [WSL 实施记录](wsl-ubuntu-setup.md)为准，其“无算法修改”只描述环境搭建阶段。

## 完成范围

| 软件项 | 本轮结果 |
|---|---|
| B1 设计 | 已落实首轮非惯性针孔双目范围；固定顺序保留真实跟踪、局部建图和地图反馈 |
| B2 可选模式 | 通过构建及短回放；默认 `native_async`，新增 `fixed_stereo`；错误模式和闭环冲突会拒绝 |
| B3 按轮建图 | 已提取完整工作单元供两种模式共用；真实关键帧、空轮、同步重置和关闭检查通过 |
| B4 顺序与时间记账 | 实际先后和单线程检查通过；原递推的时序精度验收失败，不能整体标完成 |
| B5 周期回放与采集 | 三次插桩和三次不插桩采集完整；记录、检查器和命令已交付，模型还原部分未通过 |
| B6 实用价值与概率验证 | 未进入；没有定位误差对照、分布拟合或真实可靠度预测 |

应用总计划对应状态：1 为修改后限定范围的源码/设计通过（不是原生系统适用）；2 测量契约和边界样例通过；3 本轮采集协议通过；4 时序还原失败；5—6 未执行。2026-10-15 原生直接映射失败记录不改。

## 实现与数学对象的对应

固定模式由一个线程依次调用 `System::TrackStereoFixed(k,...)` 与 `CompleteMappingRound(k)`。阶段顺序为 B(k-1) → T(k) → B(k)。前者包含图像处理、跟踪、位姿和状态返回；后者对本轮所有关键帧运行完整局部建图，空轮也执行确认。

- `LocalMapping::ProcessOneKeyFrame` 提取原 `Run()` 中的完整关键帧算法块，没有删减局部 BA、地图点或关键帧处理；原生线程和同步入口共用该块。`ProcessRound` 检查来源帧、重复关键帧和结束后的空队列。
- 固定模式不启动 LocalMapping、LoopClosing 或 Viewer 后台线程。关闭闭环时直接维护关键帧数据库，不堆积无人消费的闭环队列；未改变为纯定位模式。
- 左右特征按顺序计算，OpenCV/Eigen 限为一个线程。初次短回放发现预加载先创建了 24 线程 OpenCV 池；限制提前到加载前后，最终固定回放监测峰值为 1。原生功能对齐对照为 3；全功能参考短回放保持原默认特征线程。
- 固定 API 检查单一调用线程、轮号、T/B 配对、单调时间戳、关闭状态和活动地图。同步 reset 不再等待不存在的后台线程。原生无闭环/Viewer 对照在导出前等待建图队列并 join 工作线程。
- 初始化完整完成 T/B 后才开始 400 帧评估，原图像时间戳保留；计划释放固定为 origin+k×50 ms，不按运行结束时间改起点。全部图像预加载；这不是在线传感器部署。

范围外：惯性、鱼眼、单目、RGB-D、Viewer、闭环/地图合并/GBA、加载/保存 Atlas、交互单步、运行中定位模式切换和其他线程修改地图。异常程序退出记失败，不伪造完整轨迹。

## 验收实测

环境为 Windows 主机中的 WSL2 / Ubuntu 22.04，GCC 11.4、OpenCV 4.5.4、Eigen 3.4、Pangolin v0.6；构建并发为 2。原生 `stereo_euroc` 和新增 `stereo_fixed_replay` 均编译成功，保留上游编译警告。首次构建约 423.05 秒，边界检查补充后的增量构建约 53.55 秒。

真实图像检查：固定短回放、原生同功能范围短回放、原生默认配置短回放均退出 0；非法模式和固定模式启用闭环按预期报错。最终 selftest 通过 12 项检查，包括缺失 T/B、乱序 B、重复 B、旧接口误用、跨线程调用、重复时间戳、活动地图/完整重置、尚有 B 待完成时关闭、重复关闭和关闭后新调用。selftest 故意插入控制操作，不作为时序精度数据。

正式试运行参数在运行前固定于 [测量说明](fixed-measurement.md) / [JSON](fixed-measurement.json)：h=50 ms、H=20、tau=50 ms，100 微秒时序符合度上限，5% 插桩开销上限。H/tau 是本轮实验预算，不是道路安全需求。

| 插桩运行 | 评估帧 | 关键帧处理（含初始化） | 最大完成时间偏差 / 微秒 | 超限窗口 / 20 |
|---|---:|---:|---:|---:|
| 01 | 400 | 11 | 183.805 | 14 |
| 02 | 400 | 11 | 161.351 | 12 |
| 03 | 400 | 11 | 161.042 | 17 |

每次有 401 行事件和帧轨迹（含初始化 1 帧）、390 个空建图轮、10 个评估段关键帧轮；无重复关键帧、负时间或阶段重叠。三次不插桩运行同样完成 400 帧和 11 个关键帧。六次运行监测峰值 RSS 不超过约 868 MiB。线程数是 20 ms 采样峰值，另核对评估前后；结合固定模式源码检查，不将采样本身当成瞬时线程的穷尽证明。

插桩/不插桩评估时段均约 19.967 秒，中位数比值差约 **0.0000186%**，最慢插桩相对最快不插桩差约 **0.00406%**，低于 5%。这是预设的回放墙钟口径，含等待周期；不能由此宣称纯计算插桩成本为零。三组不足以证明任意负载下的测量扰动上界。

时钟相邻采样诊断在三次插桩运行中最大为 45、45、38 ns；它不是 OS 调度误差界。时序检查调用论文已有 `experiments/periodic-feedback/src/evaluate.py` 的 `Model.step`（即既有 g/Phi），使用独立测量的阶段耗时及每窗口初态。接口要求的 T/B 自环是该串行顺序下冗余约束，不改变所选依赖。检查器另外用准确时序样例和人为增加 200 微秒调度等待的负例核对，后者按预期失败。

## 未通过的具体原因

令 r_k 为计划释放，a_T/e_T/a_B/e_B 为实测边界，S_T=e_T-a_T、S_B=e_B-a_B。原模型要求：

\[
t_T(k)=S_T(k)+\max\{r_k,t_B(k-1)\},\qquad t_B(k)=t_T(k)+S_B(k).
\]

程序虽然按正确顺序执行，但测得

\[
\rho_k=a_T(k)-\max\{r_k,e_B(k-1)\}>0,
\qquad \eta_k=a_B(k)-e_T(k)\ge0.
\]

三次最大的 rho 分别为 183.724、161.266、160.961 微秒，eta 最大分别为 0.151、7.024、0.187 微秒。最大完成偏差几乎全部来自释放后到真正开始 T 的间隙，符合 `sleep_until` 唤醒及 OS 调度滞后的机制；尚未做内核级调度追踪，不能把这部分精确分摊到 Windows、WSL 和 Linux 调度器。

例如运行 01 的 k=73，T 偏差 183.724 微秒，B 偏差 183.805 微秒，二者相差实测阶段间隙 0.081 微秒。这是在阶段服务已经单独量出的情况下出现的漏计等待，不能把它吸收到 S 中后声称原公式精确成立。本轮不放宽 100 微秒标准。

此外，这段真实序列三次均未出现上一轮 B 延续到下一释放时刻的积压；最大 T 时延约 22.26、21.98、27.94 ms，距 50 ms 截止最少仍有 22.06 ms。所有选定窗口按记录均按时且状态有效，**只描述这批回放，不能说真实可靠度等于 1**。这也说明后续还需要更长、更有代表性的序列观测跨轮时延传播，当前数据不足以证明该模型具有实用优势。定位真值误差尚未评估。

## 文件与复现

- Windows 的 ORB_SLAM3 是源码权威，Linux 的 `/home/research/orb-fixed-work/source` 是本轮隔离副本；原 `/home/research/orb-slam3-work` 原生基线保留。60 个原生 C++/头文件/CMake 输入复核未变。
- 原始记录在 Linux `/home/research/orb-fixed-work/runs/`，包括 `pilot-instrument-01` 至 `03`、`pilot-plain-01` 至 `03` 和短回放/边界检查。CSV 时间为整数纳秒；字段见回放程序输出头。plain 中逐阶段时间为 0，不能用于时序还原。
- Windows 原始执行日志及工作副本在论文仓库忽略目录 `build/orb-fixed-2026-10-17/`。入库保存配置、脚本、精简证据及原始产物哈希；不加入图像、依赖、日志和二进制。
- 本轮 Linux 隔离工作目录约 256 MiB 实际分配（源码/词典/二进制约 245 MiB，构建约 10.4 MiB，回放小于 1 MiB）。这是新增 Linux 目录的 `du -B1` 口径，不等于 VHD 的增量；总体仍使用前期 50 GiB 预算。Windows 工作材料体积另见核验 JSON。
- 仅在 WSL Ubuntu 实测；不声称 Windows 原生或 macOS 构建通过。没有 Git add、commit、push 或分支切换。

新副本从 Windows 源码根运行 `python tools/source_snapshot.py pack --source . --output build/snapshot-NEW`，再按环境文档用 unpack 放进新的 Linux 工作根。以下命令在 Ubuntu 中执行，路径变量按机器位置设置；依赖根指向已完成原生构建的目录：

```bash
orb_tools=/mnt/d/THU/THU/research/ORB_SLAM3/tools
orb_work=/home/research/orb-fixed-work
orb_base=/home/research/orb-slam3-work
orb_paper=/mnt/d/THU/THU/research/refer-papers/manuscripts/reliability-study
bash "$orb_tools/build_fixed_stereo.sh" "$orb_work" "$orb_base" 2
python3 "$orb_tools/run_fixed_replay.py" --source "$orb_work/source" \
  --data "$orb_base/data/V1_01_easy" --output "$orb_work/runs/NEW" \
  --mode fixed --kind instrument --frames 400
python3 "$orb_tools/check_measurement.py"
python3 "$orb_tools/test_fixed_events.py" --reference "$orb_paper/experiments/periodic-feedback/src/evaluate.py"
python3 "$orb_tools/check_fixed_pilots.py" --runs "$orb_work/runs" \
  --contract "$orb_tools/../docs/fixed-measurement.json" \
  --reference "$orb_paper/experiments/periodic-feedback/src/evaluate.py" \
  --output "$orb_work/pilot-check-NEW.json"
```

完整采集按 instrument-01、plain-01、instrument-02、plain-02、instrument-03、plain-03 串行运行；汇总工具要求 `pilot-<kind>-<编号>` 目录名。续跑新批次要用新的父目录，不能覆盖本轮记录。汇总工具本轮应返回 1，表示已记录的时序验收失败，并非程序崩溃。复现只需 NumPy 及既有编译依赖，不需要拟合新的概率模型。

## 后续候选，尚未实施

优先保持数学模型与 100 微秒门槛，修改释放等待的实现，例如先睡眠、临近释放再短时间主动检查时钟；必要时再考察 CPU 亲和性。这样可能减少唤醒迟到，但增加 CPU 占用，也不保证普通 WSL 调度有硬上界，需要新批次复核。不能以当前观测最大值选择放宽后的标准。

下一次从 **B4/B5 的释放时序** 恢复：先确认候选实现及 CPU 成本记录方式，再重跑相同六次采集和时序核验；通过后才进入模式/联合分布。若始终不通过，明确保留模型与部署环境间的差别，再讨论另一种执行环境或单独的模型误差研究，不在当前论文公式中暗加随机等待项。本轮按第一处失败停止，未擅自实施这些后续方案。
