# WSL2 / Ubuntu 实施与续接记录

更新：2026-10-17。用户重启后，**WSL2、Ubuntu、开发依赖、原生编译及公开序列回放均已通过**。环境障碍已解除，固定调度模式尚未实现。计划与预算见 [wsl-ubuntu-plan.md](wsl-ubuntu-plan.md)，机器可读证据见 [wsl-ubuntu-verification.json](wsl-ubuntu-verification.json)。

## 实际完成与边界

| 环境步骤 | 本机结果 |
|---|---|
| 1 安装条件 | Windows 10 Pro 21H2，i9-12900K，约 32 GiB RAM；重启后虚拟化及两项 Windows 功能正常 |
| 2 WSL / Ubuntu | Ubuntu 22.04.5 LTS，WSL2 内核 5.10.16.3；发行版实际放在 D 盘 |
| 3 工具与资源 | GCC 11.4.0、CMake 3.22.1、OpenCV 4.5.4、Eigen 3.4.0、Pangolin v0.6；C++11 编译运行通过 |
| 4 原生构建 | DBoW2 / Sophus / g2o、ORB_SLAM3、stereo_euroc 通过；无算法源码兼容修改；动态库全部可解析 |
| 5 原生回放 | EuRoC V1_01_easy，2912 对图像、2912 行帧轨迹、90 行关键帧轨迹，退出 0 |
| 6 返回改造 | 环境前提已满足；下一项是测量契约，随后实现 B2/B3。尚未完成 B2—B6 |

原生构建耗时约 463.5 秒，回放约 163.0 秒。后者包含加载、原示例等待和虚拟显示，**不是固定周期时延实验**。本轮只核验环境及运行完整性；没有测定定位精度、真实窗口可靠度或概率假设。

## 安装与入口

没有安装完整 Linux 桌面、ROS 或 CUDA。旧版 Windows 使用系统内置 WSL 加微软官方内核 MSI，未声称安装最新 Store WSL。MSI 的 Microsoft Authenticode 签名有效，静默安装返回 0；Ubuntu 官方 rootfs 与官方 SHA256SUMS 一致，完整哈希见 JSON。

主要位置：

| 内容 | 本机位置 |
|---|---|
| Ubuntu 虚拟磁盘 | `D:\WSL\Ubuntu-22.04\ext4.vhdx` |
| 官方安装包 | `D:\WSL\downloads\` |
| 交换文件 | `D:\WSL\swap.vhdx` |
| Linux 工作目录 | `/home/research/orb-slam3-work/` |
| 正式源码 | Windows 当前 `ORB_SLAM3`，分支 `leonhardqwq`；Linux 副本不另行编辑 |
| 构建与依赖 | Linux 工作目录的 `source/`、`deps/`、`build/`、`install/` |
| 数据 | `data/V1_01_easy/`；保留一份下载 ZIP 及 manifest |
| 成功回放 | `runs/native-v101-02/`，含日志、轨迹、运行参数与 result.json |
| 原始安装记录 | 相邻论文仓库忽略目录 `build/wsl-setup-2026-10-17/resume/` |

从 Windows PowerShell 进入已装好的 Ubuntu：

```powershell
wsl -l -v
wsl -d Ubuntu-22.04
```

默认用户 `research` 已在发行版重启后实测生效。该账户没有设置密码，未开放免密 sudo；自动安装采用明确的 `wsl -u root`。若需要自行使用交互 sudo，可在 Windows 私下设置：`wsl -d Ubuntu-22.04 -u root -- passwd research`，不要把密码写入项目。

实际 Windows 用户的 `%UserProfile%\.wslconfig` 为：

```ini
[wsl2]
memory=8GB
swap=4GB
swapFile=D:\\WSL\\swap.vhdx
```

Linux 已实测约 7.8 GiB 可见内存、4 GiB swap；编译并行数为 2。没有自动重启 Windows。不要再次导入发行版、重跑功能启用脚本或删除 VHD。

首次依赖安装（已完成，日常无需重复）：

```bash
apt-get update
apt-get install -y --no-install-recommends build-essential cmake ninja-build git pkg-config ca-certificates curl python3 python3-numpy libopencv-dev libeigen3-dev libboost-serialization-dev libssl-dev libgl1-mesa-dev libglew-dev libx11-dev libegl1-mesa-dev libjpeg-dev libpng-dev libtiff-dev libopenexr-dev xvfb xauth libgl1-mesa-dri
```

这是 Linux root 安装命令。Pangolin 固定为 v0.6 / `dd801d244db3a8e27b7fe8020cd751404aa818fd`，安装在本工作目录，不覆盖系统库。ldconfig 对 WSL 自动挂载的 NVIDIA 库出现链接警告；当前 CPU / 软件渲染路线已通过，不据此声称 CUDA 可用。

## 可重跑入口

原生快照基于 `4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4`。773 个输入在 Windows、Linux 逐项 SHA-256 一致，构建后再次核验。保留当前一套构建；两个传输用 tar 和核验用重复目录已清理，清单仍保留。

源码副本工具 [source_snapshot.py](../tools/source_snapshot.py) 接收路径参数，不暂存、不切分支、不覆盖已有目录。它包括相关的未提交构建输入，排除样例图片和惯性数据；仅适用于本轮非惯性双目范围。首次建立一个新工作目录时，先在 Windows 的 ORB_SLAM3 根执行：

```powershell
python tools/source_snapshot.py pack --source . --output build/snapshot-NEW
```

再在 Ubuntu 执行（源码根路径可按本机布局替换；现有 source 不可覆盖）：

```bash
python3 /mnt/d/THU/THU/research/ORB_SLAM3/tools/source_snapshot.py unpack --archive /mnt/d/THU/THU/research/ORB_SLAM3/build/snapshot-NEW/source.tar --manifest /mnt/d/THU/THU/research/ORB_SLAM3/build/snapshot-NEW/manifest.json --destination "$HOME/orb-slam3-new/source"
bash /mnt/d/THU/THU/research/ORB_SLAM3/tools/build_native_stereo.sh "$HOME/orb-slam3-new" 2
```

现有环境直接重跑构建/回放的 Ubuntu 命令：

```bash
bash /mnt/d/THU/THU/research/ORB_SLAM3/tools/build_native_stereo.sh "$HOME/orb-slam3-work" 2
python3 /mnt/d/THU/THU/research/ORB_SLAM3/tools/replay_native_stereo.py --work "$HOME/orb-slam3-work" --output "$HOME/orb-slam3-work/runs/native-v101-03"
```

每次回放指定新的输出目录。快照打包/解包入口、构建入口均已实际执行通过；回放入口与成功运行版本逐字一致。Xvfb 提供虚拟显示，保留原示例 Viewer，不修改算法或建立完整桌面。

## 数据与首次故障

数据来自 [EuRoC 官方页](https://projects.asl.ethz.ch/datasets/euroc-mav/)及 [ETH 归档 DOI](https://doi.org/10.3929/ethz-b-000690084)，许可标记为 **In Copyright - Non-Commercial Use Permitted**。只下载 V1_01_easy，未下载整个约 6 GB 的 vicon_room1.zip。旧链接失效及新归档的 HTTP 429 均已记录；间隔重试后成功，未绕过访问限制。

下载入口 [fetch_euroc_v101.py](../tools/fetch_euroc_v101.py) 根据固定归档的 HTTP Range 取出目标成员，拒绝全包替代，校验成员大小、CRC32 和本轮固定 SHA-256，再安全解压。已有数据不重复下载；只有新目录需要：

```bash
python3 /mnt/d/THU/THU/research/ORB_SLAM3/tools/fetch_euroc_v101.py --output "$HOME/orb-slam3-new/data"
```

本轮目标 ZIP 为 1,149,702,102 字节，SHA-256：`a920fe5b5e69a6ad19b32f1cfaf90ac2f59d45dfd1ca18cc9722e07684ba45fa`。成员 CRC 与内层 ZIP 解压校验通过；**没有声称验证未下载的整个父归档 MD5**。该脚本固定归档版本，若源文件变化会拒绝，不自动换数据。

第一次原生回放失败：Windows checkout 的 V101.txt 使用 CRLF，作者的 C++ getline 把回车保留在图片名中，导致读图失败并异常退出。失败日志保留为 `native-v101-01`。第二次在运行目录生成 LF-only 时间戳副本，数值、顺序和帧数不变；原始时间戳和源码均未修改，两个输入哈希保存在 result.json。

成功回放日志报告初始化创建 545 个地图点、结束时地图有 90 个关键帧。两份轨迹均为 8 列有限数值、时间戳严格递增；帧轨迹覆盖全部 2912 帧。退出 0 不等于已证明作者 Shutdown 的线程生命周期正确，该风险仍按 B1 留给改造处理。

## 实测空间

计量时间为上述原生回放与清理完成后。Windows 文件使用 FileStandardInfo 的 AllocationSize；Linux 使用 du/df。Linux 内容已经包含在 VHD 中，不再次相加。

| 项目 | 实测 |
|---|---|
| Ubuntu ext4.vhdx | 6.562 GiB |
| swap.vhdx 当前实际文件 | 0.062 GiB，容量预算仍为 4 GiB |
| Windows 下载包 | 约 0.334 GiB |
| 已定位的 Windows WSL 内核 | 约 0.066 GiB |
| 任务日志/清单 | 约 2.3 MiB |
| 已定位新增文件合计 | **7.025 GiB** |
| Linux 文件系统已用 | 约 6.0 GiB，属于上述 VHD 内部 |
| Linux 中 ZIP + 解压数据 | 约 3.16 GiB，属于上述 VHD 内部 |

现有 Windows 源码和已有 Lean/mathlib 不计费。Windows 组件存储及 MSI 缓存的净增量没有逐项分摊，因此合计不是整个系统所有新增字节的精确总和。清理前另有约 200.6 MiB 重复传输包和约 100 MiB 核验副本；没有连续监测全过程峰值。VHD 删除内部文件后未压缩，不把内部释放量当作 Windows 文件自动缩小。保留原 50 GiB 预算、40 GiB 检查点，当前空间充足。

## 从这里继续

环境阶段已完成，下一项是 [B1 设计](fixed-schedule-design.md)第 6 节所要求的测量契约：固定 h、tau、H、初始化上限、窗口选择、截止等号、失效/无输出和测量误差规则，并执行六类边界判定。当前原生回放数据只作环境检查，不用于反过来选择让固定调度通过的阈值。

随后进入 B2/B3：可选固定模式、完整局部建图单元、数据库维护、同步重置和线程退出。再做 B4/B5 的独立开始/结束记账、三次试运行与累计时序还原，最后才检验模式/联合分布与实用价值。**本轮没有实施这些源码改动，也没有把步骤 6 标记完成。**

两处原有 Git 暂存区哈希保持不变，没有 add、commit、push 或切分支；AGENTS.md 未改。论文仓库只同步环境进展入口，理论、历史实验与组会材料未改。
