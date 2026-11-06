# 原生 KITTI 时延实验入口

普通回放工具链接原生 ORB-SLAM3 库，增加外部回放与观测。内部观测工具只在独立源码副本中插入探针，保留 Tracking、LocalMapping、LoopClosing 的算法与调度语义。基线为 `4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4`，工作分支为 `research/native-timing`。协议和研究结果位于相邻 refer-papers 仓库的 `manuscripts/reliability-study/projects/native-slam-timing/experiments/orb-slam3/native-timing/`。

KITTI 的 Rectified 配置触发上游设置打印缺陷：访问未创建的第二相机对象。随附 `rectified-settings-print.patch` 只跳过这项不适用的打印；数据标定、算法和调度不变。首次失败预跑留在 `pilot/`，修复后的检查用 `--phase pilot --attempt 2`。

另一个上游输入兼容问题在 KITTI00-02.yaml：`Viewer.ViewpointY: -100` 被要求浮点数的解析器拒绝，改成数值相同的 `-100.0`，见 `kitti-viewer-float.patch`。首个 01 正式尝试失败后修复，原失败保留，论文侧 `provenance/config-amendment.json` 记录配置冻结的这一项修订。其他配置与二进制不变；补跑独立保存，分析时用 `--additional-runs` 同时纳入原始失败和补跑结果。

## 2026-10-27 实测结果

本轮已完成采集与总结，入口为相邻论文仓库的 [结果说明](../../../refer-papers/manuscripts/reliability-study/projects/native-slam-timing/experiments/orb-slam3/native-timing/results/kitti-native-2026-10-27/README.md)。有效设置下 30 次正式重复中，29 次完整完成、1 次周期 01 在 SO3 指数计算收到 NaN 后异常退出；后者没有通过补跑替换。完整周期运行的最大释放到返回时延为 44.615 ms，100 ms 截止下未观测到超时，结论以运行完整完成为条件。

NaN 的最初来源尚未定位，后续诊断应另开批次保留尝试。原始帧、资源与失败日志保存在 WSL 工作根，并已打包；论文侧只保留约 3.13 MB 的配置、来源和精简结果。新一轮采集应使用新的 batch 名，先对每份不同的原配置做一次短启动检查。

## 复现

下列构建从固定上游基线导出，再应用两份兼容补丁。若导出的是本分支已经修复的提交，不要重复应用补丁。使用新的空目录重建，不向已有实验目录覆盖源码或产物。

使用已有 WSL Ubuntu 22.04 工具链：GCC 11、CMake、Eigen、OpenCV 4.5、兼容的 Pangolin。工作根与依赖路径由使用者设置，下列是 Linux shell 命令；所有大数据、构建和运行结果留在独立工作根。不要在正式计时期间并行下载、编译、分析或运行其他实验。

```bash
NATIVE_ROOT="$HOME/orb-native-timing-work"
ORB_REPO="/absolute/path/to/ORB_SLAM3"  # 设置为本机源码根
PAPER_NATIVE="/absolute/path/to/refer-papers/manuscripts/reliability-study/projects/native-slam-timing/experiments/orb-slam3/native-timing"
PANGOLIN_CONFIG="$HOME/orb-slam3-work/install/lib/cmake/Pangolin"
mkdir -p "$NATIVE_ROOT/source" "$NATIVE_ROOT/tools" "$NATIVE_ROOT/logs"
git -C "$ORB_REPO" archive 4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4 | tar -x -C "$NATIVE_ROOT/source"
cp "$ORB_REPO/tools/native-timing/"* "$NATIVE_ROOT/tools/"
patch -d "$NATIVE_ROOT/source" -p1 < "$NATIVE_ROOT/tools/rectified-settings-print.patch"
patch -d "$NATIVE_ROOT/source" -p1 < "$NATIVE_ROOT/tools/kitti-viewer-float.patch"
tar -xf "$NATIVE_ROOT/source/Vocabulary/ORBvoc.txt.tar.gz" -C "$NATIVE_ROOT/source/Vocabulary"
cmake -S "$NATIVE_ROOT/source/Thirdparty/DBoW2" -B "$NATIVE_ROOT/builds/dbow2" -DCMAKE_BUILD_TYPE=Release
cmake --build "$NATIVE_ROOT/builds/dbow2" -j2
cmake -S "$NATIVE_ROOT/source" -B "$NATIVE_ROOT/builds/native" -DCMAKE_BUILD_TYPE=Release -DPangolin_DIR="$PANGOLIN_CONFIG"
cmake --build "$NATIVE_ROOT/builds/native" --target g2o -j2
cmake --build "$NATIVE_ROOT/builds/native" --target stereo_kitti -j2
cmake -S "$NATIVE_ROOT/tools" -B "$NATIVE_ROOT/builds/observer" -DORB_SOURCE="$NATIVE_ROOT/source" -DPangolin_DIR="$PANGOLIN_CONFIG" -DCMAKE_BUILD_TYPE=Release
cmake --build "$NATIVE_ROOT/builds/observer" -j2
python3 "$NATIVE_ROOT/tools/acquire_kitti.py" --output "$NATIVE_ROOT/data/kitti"
cp "$PAPER_NATIVE/configs/protocol.json" "$NATIVE_ROOT/protocol.json"
# 新采样先修改该副本的 batch 字段；保留原值只用于恢复相应历史批次。
python3 "$NATIVE_ROOT/tools/run_batch.py" --root "$NATIVE_ROOT" --protocol "$NATIVE_ROOT/protocol.json" --phase pilot
python3 "$NATIVE_ROOT/tools/run_batch.py" --root "$NATIVE_ROOT" --protocol "$NATIVE_ROOT/protocol.json" --phase overhead
# 检查短预跑的计时与质量、观测开销之后：
python3 "$NATIVE_ROOT/tools/run_batch.py" --root "$NATIVE_ROOT" --protocol "$NATIVE_ROOT/protocol.json" --phase formal
python3 "$NATIVE_ROOT/tools/analyze.py" --runs "$NATIVE_ROOT/runs/kitti-native-2026-10-27/formal" --data "$NATIVE_ROOT/data/kitti" --output /path/to/compact-results
python3 "$NATIVE_ROOT/tools/plot_results.py" /path/to/compact-results
```

分析需要 NumPy；绘图另需 matplotlib。可在 Windows 的已有分析环境绘图；读取 WSL 文件时使用该环境支持的 WSL 共享路径。工具不执行 Git 暂存或提交。`run_batch.py` 重现新批次时修改协议中的 `batch`，避免覆盖旧输出；续跑只跳过已结束的尝试，不把失败静默换成成功样本。

## 输出的准确含义

`frames.csv` 的执行时刻以构造 System 之后的单调时钟为原点；`dataset_s` 保留原始数据时间。

- `release_s`：数据时间相对首帧。在 periodic 回放中是实际执行的逻辑释放计划；upstream 回放中仅供对照，不计算持续输入可靠度。
- `read_begin_s` / `read_end_s`：双目读取与解码开始／完成。
- `track_begin_s` / `track_end_s`：可选原始缩放结束后的 TrackStereo 调用边界。
- `state`：原生 GetTrackingState 返回值，2 为 OK；初始化、丢失等状态全部保留。
- `pose0` 至 `pose11`：本次调用返回 Tcw 的逆矩阵 Twc 前三行，按行排列。状态不为 OK 时不当成有效定位。
- `map_changed`：上游大地图变更标志，不等于地图 ID，也不等于重置计数。
- `probe_us`：状态、地图标志与位姿整理耗时；`previous_write_us` 为上一帧 CSV 记录耗时。最后一帧写入包含在 runner.json 的总量中。格式化和写入在调用计时之外，但会影响下一帧等待。

periodic 下 `W=read_begin-release`、`S=track_end-read_begin`、`D=track_end-release=W+S`。图像已存磁盘，逻辑释放不意味着实测相机接收，更不代表传感器到控制执行器时延。upstream 按原示例在调用后休眠 `max(0,相邻数据时间差-调用耗时)`，读图和观测时间额外存在。

Viewer 关闭；核心后端仍并发执行。上游 Shutdown 的等待线程退出部分被注释，因此 `backend_drained=false`。不使用退出时重新导出的轨迹替代在线结果，也不把后端完成算进当前调用。

## 分析边界

每个新进程是一次重复；同一视频的帧和滑动窗口有关联。五次重复只给描述性中位数与范围，不给伪独立的二项置信区间。所有帧为主结果；前 10 秒与其后另列。所选三个序列不代表独立抽取的全部驾驶场景。

ATE 只做 SE(3) 对齐、不拟合尺度。状态回到初始化后另划地图片段；出现片段时整段单坐标 ATE 不适用，另报各片段结果。大地图变更不是完整的重置探针，必须结合原日志检查潜在漏检。1 秒 RPE 仅为诊断，非 KITTI 标准的 100–800 m 相对误差评测。有效率与时序成功率分开报告，并给二者同时满足的窗口率。100/200/500 ms 是研究敏感性门槛，不是车载安全指标。

原数据、逐帧日志、源码快照和二进制留在 WSL 工作根；Git 保留工具、协议、来源摘要、精简 CSV/JSON 与选定图表。下载采用官方公开 S3 对象的范围请求，验证所选成员 CRC 并保存 SHA256 清单；未下载的整包不宣称通过整体校验。

## 2026-10-29 内部计时与跨轮反馈

已完成三个 KITTI 序列各三次的原生内部观测，共 14,889 帧，另有 100 帧预跑和三组记录开关对照。分析报告见论文侧[分布、时间预测、内部耗时与跨轮反馈](../../../refer-papers/manuscripts/reliability-study/projects/native-slam-timing/experiments/orb-slam3/native-timing/extended-results-2026-10-29.md)，构建、复算及原始归档说明见[本批结果](../../../refer-papers/manuscripts/reliability-study/projects/native-slam-timing/experiments/orb-slam3/native-timing/results/kitti-trace-2026-10-29/README.md)。

新增工具 `tools/native-timing/prepare_trace.py` 在独立源码副本中插入可关闭的阶段与地图版本探针，`run_trace_batch.py` 负责串行重复与保存失败；仓库中的算法源码未直接插入这些探针。独立工作目录为 `~/orb-native-timing-work/trace-2026-10-29/`，与旧基线构建和运行分开。左右提取按重叠区间计量，嵌套阶段不重复相加；后台退出时的未闭合区间作为删失保留。

观测配对到 5,938 条“Tracking 产生关键帧—后台更新地图—后续 Tracking 读取版本”的跨轮反馈。多数轮距为 1–2 帧，全局优化相关反馈最长为 67 帧。这是实际任务关系的证据，固定两轮历史和给定模式的耗时条件律仍需另外检验。新增九次运行未中断，100 ms 下未见超时，旧批次的 NaN 起因尚未定位。

## 历史工具的适用范围

提交 `5382b1dae8b11aeaa50ce107f8c5ff38164a3370` 保存了 2026-10-27、10-29 实验使用的工具。该提交的旧 `run_trace_batch.py` 固定使用 `trace-2026-10-29/`、01/05/07 各三次、07 预跑与三组开关对照；它读取并冻结协议，但任务参数并非由协议驱动。此版本用于追溯历史运行，不应用于启动新批次，也不应据其退出码判定事件记录完整。当前版本已修复观测批次管理，见下一节；历史提交和实验结果保留。`run_batch.py` 仍为首批历史工具，本轮没有扩展其运行管理。

`plot_results.py` 是首批 01/05/07、五次重复及 100/200/500 ms 门槛的专用绘图入口；调整研究设置时需要另行核对分析和图表，不能仅替换输入目录。


## 新的内部观测批次

当前 `run_trace_batch.py` 要求显式传入 `--work`，不再默认写入旧 `trace-2026-10-29`。`--root` 指向含 `data/kitti` 的原生运行根，`--work` 指向本批构建目录，内含 `source-v2`、`observer/native_kitti`，输出位于其 `runs/<phase>/`。两者均在启动时转为绝对路径。

协议沿用论文侧 `extended-analysis-2026-10-29.json` 的结构。新批次先复制为新协议文件并改 `batch` 标识；`batch` 用于记录，实际目录由 `--work` 决定。`instrumentation_plan` 中下列参数实际驱动任务：

| 参数 | 执行含义 |
| --- | --- |
| `sequences`、`repetitions` | 正式阶段的序列与每序列重复次数 |
| `pilot_frames`、`pilot_sequence` | 预跑帧数与序列；序列默认采用 `overhead_sequence` |
| `overhead_sequence`、`overhead_frames`、`overhead_pairs` | 记录开关对照的序列、帧数与配对数；每对交替开关顺序 |
| `formal_frames` | 正式运行帧数上限；默认 0 表示完整序列 |
| `seed` | 每个重复块内序列顺序的随机种子，默认 20261029 |
| `timeout_seconds`、`pause_seconds` | 每次启动至退出的超时阈值、相邻尝试间隔；默认 1800 与 5 秒 |

`retain_native_scheduling` 必须为 `true`；`playback` 只接受 `periodic` 或历史写法 `periodic, original KITTI timestamps`。回放固定为灰度双目、完整观测、关闭 Viewer，不清缓存、不主动等待后台排空。`record`、`outputs`、`topology_focus` 是说明文字，不动态开关探针；实际事件集合仍由 `prepare_trace.py` 决定。其他未知执行字段会被拒绝。序列 00–02、03、04–12 分别选择对应的上游配置；是否已下载所选数据需另行核对。

下面是 Linux/WSL 的构建与运行模板。使用新的空目录和协议副本；`NATIVE_ROOT/source` 应是前文准备好的兼容修复基线。

```bash
ORB_TOOLS="$ORB_REPO/tools/native-timing"
TRACE_WORK="$NATIVE_ROOT/trace-new-batch"  # 改为本次独立批次目录
NEW_PROTOCOL="/absolute/path/to/new-trace-protocol.json"
# 从论文侧配置复制到 NEW_PROTOCOL，修改 batch 和实际采样参数后继续。
python3 "$ORB_TOOLS/prepare_trace.py" --base "$NATIVE_ROOT/source" --output "$TRACE_WORK/source-v2"
cmake -S "$TRACE_WORK/source-v2" -B "$TRACE_WORK/build" -DCMAKE_BUILD_TYPE=Release -DPangolin_DIR="$PANGOLIN_CONFIG"
cmake --build "$TRACE_WORK/build" --target ORB_SLAM3 -j2
cmake -S "$TRACE_WORK/tools" -B "$TRACE_WORK/observer" -DORB_SOURCE="$TRACE_WORK/source-v2" -DCMAKE_BUILD_TYPE=Release -DPangolin_DIR="$PANGOLIN_CONFIG"
cmake --build "$TRACE_WORK/observer" -j2
python3 "$ORB_TOOLS/run_trace_batch.py" --root "$NATIVE_ROOT" --work "$TRACE_WORK" --phase pilot --protocol "$NEW_PROTOCOL"
python3 "$ORB_TOOLS/run_trace_batch.py" --root "$NATIVE_ROOT" --work "$TRACE_WORK" --phase overhead --protocol "$NEW_PROTOCOL"
# 检查预跑与观测开销后，再启动正式阶段。
python3 "$ORB_TOOLS/run_trace_batch.py" --root "$NATIVE_ROOT" --work "$TRACE_WORK" --phase formal --protocol "$NEW_PROTOCOL"
```

每阶段冻结完整协议、实际执行参数、任务列表、绝对路径，以及程序、库、词袋、对应配置、时间戳和运行脚本的 SHA256。图像内容仍依赖已有下载清单，本次不逐图重新计算哈希。新格式不会接管旧格式冻结目录；续跑时任何冻结项变化都会拒绝，失败记录不被覆盖或重跑。已经存在但缺少完整元数据的运行目录也不会覆盖。

`completed` 要求退出码为 0、帧表数量及时间边界有效、`runner.json` 完成信息一致；开启观测时还要求事件 CSV 结构有效、存在时钟原点和对应数量的帧身份记录、每个输入帧各有一个先后有效的调用起止事件。这只验证记录完整性，不等于定位质量通过，也不检验所有内部事件的语义。后台未闭合区间可以是正常退出时的删失，保留在原数据中。

启动失败记录为 `start_error`，非零退出为 `execution_error`，缺失或损坏输出为 `output_error`，超时为 `timeout`，可捕获中断为 `interrupted`。异常信息、已产生的帧数和日志均保留；结果以临时文件加替换的方式写入。超时先终止进程组，5 秒后仍未退出则强制结束并回收。Ctrl+C 或 SIGTERM 会尝试收尾；断电、SIGKILL 等不可捕获中断仍可能留下 `running`，需人工检查进程和日志，再使用新目录重试，不能直接改成成功。

`finished.json` 列出计划数、已读取／执行的尝试数、各状态计数和 `all_completed`，文件存在本身不代表全部成功。批次含失败时返回非零；中断返回 130。新运行脚本从 Linux/WSL 启动，Windows 仅运行可移植的管理逻辑测试。

恢复旧工具可从历史提交导出到一个新建空目录，不切换当前工作分支：

```bash
HIST_TOOLS="/absolute/path/to/new-historical-tools"
mkdir -p "$HIST_TOOLS"
git -C "$ORB_REPO" archive 5382b1dae8b11aeaa50ce107f8c5ff38164a3370 tools/native-timing docs/native-timing AGENTS.md | tar -x -C "$HIST_TOOLS"
```

历史归档的恢复和复算仍按论文侧结果说明执行；不要用当前 runner 续写历史冻结批次。

## 本次管理修复检查（2026-11-07）

从仓库根执行 `python -B tools/native-timing/test_run_trace_batch.py -v`（Linux 使用 `python3`）。只依赖标准库，以临时目录和短 Python 子进程检查：协议驱动任务、配置选择、冻结输入与拒绝覆盖、正常输出、跟踪丢失和后台删失保留、缺帧／缺完成信息／缺事件、坏事件记录、非零退出、启动失败、超时回收、中断收尾和失败批次汇总。

- Windows Python 3.13.13：16 项中 15 项通过，1 项 POSIX 专用测试跳过。
- WSL2 Ubuntu 22.04 / Python 3.10.12：16 项全部通过，包括进程忽略 SIGTERM 后的强制终止。
- 只读检查旧 `trace-2026-10-29/runs` 的 16 次运行（9 次正式、6 次开关对照、1 次预跑），均通过新输出校验；未修改这些记录。
- 历史工具在独立提交中保留；六个原有 Python 脚本语法、迁移后的证据链接及补丁对应关系已检查。

本次没有重新编译或运行 ORB-SLAM3，也没有重算时延研究结果；以上是批次管理逻辑与既有记录兼容性的检查。
