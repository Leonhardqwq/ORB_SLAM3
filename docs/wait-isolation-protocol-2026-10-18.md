# 不含 SLAM 的释放等待对照

2026-10-18，执行前冻结。目的为定位当前 WSL 平台的尾部启动间隙；本批不是 B4/B5 的真实 SLAM 验收。

参数以[JSON](wait-isolation-protocol-2026-10-18.json)为准。周期 50 ms，每次 800 轮；空工作与 20 ms 墙钟模拟计算分别采用普通休眠、提前 500 µs 唤醒并主动检查，各重复三次，共12次无诊断基准。第二阶段仅主动检查，两种工作量各三次，单独开启诊断与内核追踪，共6次。每次轮换条件顺序，串行运行，保留全部结果。没有新增绑核、实时优先级或全局时钟设置。

程序不导入 SLAM 或 OpenCV；模拟计算是整数循环，持续约20 ms墙钟，并非固定20 ms CPU计算。每轮启动间隙为 `start-max(release,previous_end)`。同时保留相对释放时刻的迟到、实际工作时间、进程CPU比例。逐轮间隙不代替原论文的累计窗口还原误差；100 µs只作诊断对照，任务截止仍为50 ms。

诊断档采集首次返回读钟、主动检查退出、最大相邻读钟间隔、线程CPU、非自愿切换与所在CPU。`CLOCK_MONOTONIC_RAW`用于交叉检查，端点与主时钟不完全相同，不把两者差或CPU差解释成精确抢占时长。所有探针开销保留。

WSL 内核追踪使用独立实例、`mono`时钟和每CPU 2 MiB缓冲，仅启用涉及探针PID的切换、唤醒、迁移以及中断/软中断事件。探针以普通research用户运行。保存事件与丢失计数；结束后关闭并删除本次实例，若本次挂载tracefs则卸载。不修改默认追踪器及全局调度。

实施中增加必要的采集正确性检查：WSL发行版PID可能与内核追踪的PID不同，用子进程自身写入的 `trace_marker` 确定追踪编号。正式结果必须捕获休眠/唤醒事件作为正对照。首次使用发行版PID的追踪为空，作为采集失败保留，使用相同二进制和实验参数在 `traced-v2` 独立重跑；分析时指定 `--traced-dir traced-v2`。不能把空追踪解释为未发生调度事件。

Windows短时取证先检查无既有WPR记录，使用独立实例和有界缓冲，成功开启的记录由本任务关闭。宿主和来宾的时间与处理器映射未核验前，不把同时出现的现象称为因果。宿主调度事件不能自动代表Hyper-V虚拟处理器调度。

短时宿主取证成功后、正式追踪批次开始前，冻结宿主附加采集：六次追踪运行分别保存WPR，使用 `tools/wait_isolation_host.wprp` 的64 MiB内存缓冲。WSL追踪为每CPU 2 MiB；本机24个逻辑处理器最多约48 MiB，两类缓冲合计约112 MiB，另有元数据开销。每次运行停止并保存，检查丢事件和记录时间覆盖，不以有限缓冲自动保证完整。未对基准阶段启用追踪。

## 复现

Linux / WSL中使用已有g++和Python3；从ORB仓库根执行，输出路径自行指定为新目录：

```sh
g++ -O3 -Wall -Wextra -Werror -std=c++11 tools/wait_isolation_probe.cc -pthread -o /path/to/wait_isolation_probe
python3 tools/run_wait_isolation.py --binary /path/to/wait_isolation_probe --protocol docs/wait-isolation-protocol-2026-10-18.json --out /path/to/new-run/baseline --phase baseline
# 追踪阶段需root权限，但被测进程仍降权运行；普通基准不需要root。
sudo python3 tools/run_wait_isolation.py --binary /path/to/wait_isolation_probe --protocol docs/wait-isolation-protocol-2026-10-18.json --out /path/to/new-run/traced --phase traced --research-user research
python3 tools/analyze_wait_isolation.py --root /path/to/new-run --out /path/to/new-summary.json
```

WSL下同时采集宿主记录时，给追踪命令增加 `--host-wpr /mnt/c/Windows/System32/wpr.exe --host-profile "D:/path/to/wait_isolation_host.wprp" --host-out "D:/path/to/existing/new-host-output"`。后两项采用Windows绝对路径，由运行者提供；先建立新的输出目录，不能指向历史批次。需要Windows追踪权限，失败保留命令和错误。分析ETL时使用已有Windows Performance Toolkit的 `xperf -i file.etl -a tracestats` 等入口；普通Linux实验不依赖WPR。

基准及追踪是两类证据，不能混算通过比例。若仍无确定的可修改原因，不盲目加长主动等待或削减视觉算法；B4/B5保留未通过，停止模式/联合分布拟合。若提出新的策略，先冻结条件，再用关闭诊断的真实SLAM回放核验质量、资源与共用任务代价。

## 本地定时器中断补查

常规irq_handler事件不覆盖所有APIC向量。检查有效主追踪后另行冻结[补查参数](wait-isolation-irq-vectors-2026-10-18.json)，使用相同二进制、相同800轮和500 µs主动检查，在无计算/20 ms模拟计算下各一次，增加local_timer、reschedule、call_function、irq_work等可用向量的入口/出口；不同时启用宿主WPR。用主入口的 `--phase traced`、补查协议及新的`irq-vectors`输出目录运行。分析主批次时另加 `--extra-traced-dir irq-vectors`。这是排查事件覆盖遗漏，不能与主批次混算性能重复或据此宣布时序保证。

## 宿主记录保留范围修正

实测发现64 MiB环形记录只保留末尾约5秒，尽管丢失计数为0。再次冻结[流式补查参数](wait-isolation-host-stream-2026-10-18.json)，两种工作量各一次，使用相同探针和向量事件。给宿主追踪命令增加 `--host-filemode --host-temp-dir "D:/path/to/new-temp" --host-instance ORBWaitUniqueName`，宿主输出使用新的目录，Linux输出为新的 `host-stream`；分析时增加 `--host-stream-dir host-stream`。WPR配置中分别提供Memory/File两种配置，初始Memory配置与最终配置差异见[补丁](wait-isolation-host-profile.patch)。

本次外层任务脚本检查至少6 GiB可用空间，每秒统计临时与最终记录，超过2 GiB就关闭指定名称的本任务WPR会话；实际未触发。通用Linux入口只负责记录与清理，不自动执行Windows磁盘监控，重跑流式采集需配套容量监控或预留空间。实际命令、峰值和临时监控脚本保存在任务缓存，精简值在结果JSON中。检查 `xperf -a tracestats -timespan actual` 的首末事件和首个可靠事件；不能只凭零丢事件判定全程保留。
