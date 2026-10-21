# WSL2 + Ubuntu：环境、预算与逐步验收

2026-10-17 用户批准执行。关联：[软件改造 B1—B6](fixed-schedule-plan.md)、[已完成的 B1 设计](fixed-schedule-design.md)。实施状态与续接入口统一见 [wsl-ubuntu-setup.md](wsl-ubuntu-setup.md)，机器可读证据见 [wsl-ubuntu-verification.json](wsl-ubuntu-verification.json)。

## 目标和边界

在当前 Windows 电脑建立 WSL2 + Ubuntu 22.04，构建并回放原生 ORB-SLAM3，再恢复 B2—B6。原模型和视觉算法不因环境配置而改变。环境成功不等于固定调度、概率假设或实际价值已经通过。

用户已授权本计划的安装与配置；需要重启时先保存记录，由用户保存工作后手动重启，不自动重启。遇到第一项无法通过的验收，记录原因与恢复方式后停止依赖该步骤的工作。普通配置错误可在当前步骤内修复。

保留既有仓库、分支、未提交修改和暂存区。本次不 add、commit、push、切换或重置分支。文档入库指放入可跟踪的工作区文件，不代表自动提交。

## 文件位置与源码管理

| 内容 | 位置 | 管理 |
|---|---|---|
| Ubuntu 虚拟磁盘 | `D:\WSL\Ubuntu-22.04\` | 新增 Linux 环境，不进 Git |
| WSL 交换文件 | `D:\WSL\swap.vhdx` | 4 GiB 预算，不进 Git |
| Windows 资源配置 | 实际登录用户的 `%UserProfile%\.wslconfig` | 首次写前检查；已有配置不覆盖 |
| 正式代码 | 现有 `ORB_SLAM3`，`leonhardqwq` 分支 | 唯一编辑与 Git 来源 |
| 构建副本 | Ubuntu `~/orb-slam3-work/source/` | 从正式源码按清单生成，不另行编辑/提交 |
| 依赖、构建、数据、原始日志 | Ubuntu `~/orb-slam3-work/` 下独立目录 | 不进 Git，大数据不重复复制 |
| 安装阶段原始记录 | 相邻论文仓库 `build/wsl-setup-2026-10-17/` | 已被忽略；Linux 可运行后转入专用工作目录 |
| 计划、配置、脚本与精简证据 | 本仓库 docs、tools | 可入 Git |

生成 Linux 源码副本时记录基准提交、实际工作区文件清单与 SHA-256；包含需要的未提交源码及明确选择的新增文件，不复制 `.git`、历史输出或整个研究目录。构建使用 Linux 文件系统。不要将 Linux 副本回灌覆盖 Windows 用户改动。

WSL 是按 Windows 用户注册的：必须核对实际登录用户，不能在工具的 sandbox 账户下创建发行版。共享系统功能可以用管理员权限启用。

## 六步执行

| 步骤 | 工作 | 验收标准 |
|---|---|---|
| 1 安装条件 | 检查 Windows 版本、硬件虚拟化、可选功能、现有发行版、用户和磁盘基线 | 支持 WSL2，目录及账户明确，不覆盖既有环境 |
| 2 WSL 与 Ubuntu | 启用 WSL/VirtualMachinePlatform，不自动重启；安装 WSL 运行组件和 Ubuntu 22.04；创建普通 Linux 用户，主要数据放 D 盘 | Ubuntu 可启动，`wsl -l -v` 为版本 2，实际磁盘位于计划路径 |
| 3 工具与资源 | 内存 8 GiB、swap 4 GiB；安装 Linux 工具链及必要开发依赖，记录版本 | C++ 小程序可运行；CMake 能找到依赖 |
| 4 原生构建 | 生成源码副本，编译 DBoW2/g2o/Sophus、ORB-SLAM3 和双目入口 | 实际构建成功；兼容改动有完整差异，不混入算法变化 |
| 5 原生回放 | 仅下载一个公开双目序列，记录来源/许可/哈希，保存轨迹与退出状态 | 实际处理图像，完成初始化/跟踪/建图并正常结束，有可检查结果 |
| 6 返回改造 | 更新环境阻塞，冻结应用步骤 2 的测量契约，再执行 B2—B6 | 不跳过时序、分布或实用价值验收，不把原生回放当固定模式通过 |

Ubuntu 安装方法取决于实际 WSL 版本：优先支持指定位置的官方安装方式；否则使用官方 Ubuntu 根文件系统导入指定位置。核验下载来源和哈希，不默认先在 C 盘安装整套系统再搬迁，不 unregister 或删除已有发行版。

Windows 功能若处于 EnablePending 或工具明确要求重启，就在此暂停；禁止尝试用多次安装绕过重启。重启后重新检查功能状态，再安装发行版。若发现 BIOS 虚拟化未启用，给出手动操作说明后停止。

## 依赖与构建范围

安装 C/C++ 编译器、CMake、Git、pkg-config、OpenCV、Eigen、Boost Serialization、OpenSSL 及 Pangolin 必要依赖。DBoW2、g2o、Sophus 优先用工程版本；Pangolin 固定经核验的提交或版本，不直接追随最新开发分支。

即使关闭 Viewer，当前工程仍需要 Pangolin 编译依赖。首轮不安装 ROS、CUDA、深度学习环境、完整 Ubuntu 桌面，不接真实相机。首次可先采用无显示回放；需要改入口关闭 Viewer 时独立记录改动。原生健康检查与关闭闭环后的等功能对照分开：LC 队列/数据库问题仍须按 B1 设计处理。

兼容修复限定为构建、依赖 API 等必要范围，保留原始源码与完整差异。需要改变视觉算法时另行说明，不能以构建修复名义静默改变。

## 磁盘与资源预算

口径是本轮实际新增空间，已有 Windows 源码不重复计费；Linux 副本计费。

| 内容 | 首轮预估 |
|---|---|
| WSL、Ubuntu 与基础更新 | 4–6 GiB |
| Linux 工具链与开发依赖 | 4–8 GiB |
| 源码副本、词袋与编译文件 | 2–5 GiB |
| 一个序列的解压数据 | 3–6 GiB |
| 日志与结果 | 0.5–1 GiB |
| swap | 4 GiB 预留 |
| 下载、安装、构建临时空间 | 额外 5–10 GiB |

目标为长期保留约 20–35 GiB、峰值约 30–45 GiB，预留 50 GiB。初始内存上限 8 GiB、swap 4 GiB、编译并行数 2。这些是预算，不是已占用量或保证值。

基础系统、依赖、构建、下载数据完成后分别计量。新增累计接近 40 GiB 时先检查占用；预计超过 50 GiB 时停止扩容并报告。保留一套主要构建结果，不提前下载全数据集。原始日志、缓存按精确目录忽略，不全局忽略 JSON/CSV。

分别记录 Windows 上 VHD 的实际占用和 Linux 内部文件使用量；删除内部文件不代表 VHD 自动缩小。整盘空闲空间变化可能包含其他程序活动，不能把全部变化当成本任务精确占用。

## 文件交付与恢复

- `docs/wsl-ubuntu-plan.md`：本计划及冻结的预算、验收。
- `docs/wsl-ubuntu-setup.md`：实际命令、版本、进度、故障、重跑与恢复步骤。
- `docs/wsl-ubuntu-verification.json`：精简机器可读结果；未完成项如实标记。
- `tools/`：必要时提供可重跑的检查/启用/源码副本与运行脚本，不能用脚本存在代替执行通过。
- docs README、固定调度计划、历史进度增加入口；论文仓库仅增入口和状态，不复制维护全部安装细节。

最终只报告实际验证的平台、构建、回放与新增空间。WSL2 中的回放性能不直接代表车载 Linux 硬件性能。

官方操作依据：[安装](https://learn.microsoft.com/windows/wsl/install)、[手动启用组件](https://learn.microsoft.com/windows/wsl/install-manual)、[资源配置](https://learn.microsoft.com/windows/wsl/wsl-config)、[虚拟磁盘](https://learn.microsoft.com/windows/wsl/disk-space)。安装时以本机工具支持的参数为准。
