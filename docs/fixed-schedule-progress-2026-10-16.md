# 六步软件改造执行记录

日期：2026-10-16。执行依据：[B1—B6 计划](fixed-schedule-plan.md)及应用总计划的“遇到第一项验收不通过即停止”。

## 本轮结果

已完成 [B1 源码与接口设计](fixed-schedule-design.md)。开始检查 B2 的原生构建前提，CMake 在 OpenCV 查找阶段失败，尚未编译 ORB-SLAM3。按验收规则停止依赖该环境的后续工作。**本轮没有修改 SLAM 的 C++ 实现，没有得到可运行的固定调度模式，也没有真实数据实验结果。**

| 阶段 | 实际状态 | 不能据此声称的内容 |
|---|---|---|
| B1 | 源码对应、任务边界、接口与异常处理设计完成，设计自查通过 | 实际时序已经符合模型 |
| B2 | 前置配置检查未通过，尚未进入模式实现 | 原生/固定模式构建运行通过 |
| B3 | 未执行 | 完整按轮次建图已经实现 |
| B4 | 未执行 | 墙钟间隙、抢占和累计时序误差已经可控 |
| B5 | 未执行 | 测量契约已冻结、已有三次试运行 |
| B6 | 未执行 | 定位质量、吞吐或真实可靠度已经验证 |

## 构建证据

源码 HEAD 为 `4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4`，分支 `leonhardqwq`。原生算法文件未修改。Windows 本机检查使用 CMake 3.31.3、显式指定的 MinGW GCC/G++ 14.2.0 和 Ninja；不使用 PATH 中另一个 clang 15.0.0 的 g++ 包装器。

实际结果：C/C++ 编译器 ABI 和 C++11 检查通过，`find_package(OpenCV 4.4)` 找不到 `OpenCVConfig.cmake` / `opencv-config.cmake`，随后退出码 1：

```text
CMake Error at CMakeLists.txt:35 (message):
  OpenCV > 4.4 not found.
-- Configuring incomplete, errors occurred!
```

精简证据及源码 SHA-256 保存在 [环境检查 JSON](fixed-schedule-environment-2026-10-16.json)。原始 configure.log、environment.json 和 CMake 缓存保存在相邻论文仓库被忽略的 `build/orb-slam3-preflight-2026-10-16/`，不默认入 Git。另一次先行手工配置同样在 OpenCV 处失败，其缓存位于 `build/orb-slam3-baseline-2026-10-16/`，不作为另一种环境通过的证据。

以下检查的证据范围必须保持：

- 在 `D:/CPP_env`、`D:/Qt` 与本源码内的定向搜索未找到三种依赖的 CMake config；没有遍历整台机器，不能断言全机绝无 OpenCV/Eigen/Pangolin。
- CMake 停在 OpenCV，因此 Eigen、Pangolin、Boost、OpenSSL 等依赖没有完成配置核验。
- 当前 CMake 直接链接 DBoW2/g2o 的 `.so`，源码有 POSIX `usleep`。原 README 的实测平台为 Ubuntu。Windows 直接移植可能需要额外构建改动，不能承诺只设置 OpenCV_DIR 就能运行。
- `wsl --list --quiet` 返回码 1 和安装/帮助说明，未得到可运行发行版证据；没有据此安装 WSL，也未验证 Linux 或 macOS。
- 没有使用 Python cv2、伪头文件或空库代替 C++ 开发依赖；没有以单独调度模拟器代替视觉工程运行验收。

## 重跑检查

入口：[check_fixed_schedule_environment.py](../tools/check_fixed_schedule_environment.py)。只配置，不安装、不清理、不构建、不修改 Git。每次指定新的输出目录，保留上次证据。通用参数如下；编译器和 Ninja 路径按执行机器传入：

```text
python tools/check_fixed_schedule_environment.py --source . --output build/preflight-NEW --cc <C编译器> --cxx <C++编译器> --ninja <Ninja>
```

本轮实际命令（工作目录为相邻论文仓库 `manuscripts/reliability-study`；本轮在交付暂存目录运行同一脚本，源码已逐字交付到 fork）：

```text
python -B build/orb-slam3-b1-delivery/payload/tools/check_fixed_schedule_environment.py --source D:/THU/THU/research/ORB_SLAM3 --output build/orb-slam3-preflight-2026-10-16 --cc D:/CPP_env/mingw64/bin/gcc.exe --cxx D:/CPP_env/mingw64/bin/g++.exe --ninja D:/CPP_env/mingw64/bin/ninja.exe
```

退出 0 也只表示 CMake 配置完成，仍须编译第三方库、ORB-SLAM3、回放入口并实际运行，才能通过 B2 的原生基线要求。若已有兼容 OpenCV 安装，可在环境中设置 OpenCV_DIR/CMAKE_PREFIX_PATH 后重跑；其余依赖仍须逐一核验。

## 下次从哪里接着做

1. **先解决构建环境**：优先在已有、可访问的 Linux 开发环境核验官方原生基线；若继续本机 Windows，则先明确完成 C++ 依赖与构建移植的范围。当前没有选择或部署新的运行环境，不把移植工作隐藏在模型改造里。
2. 构建通过后，用公开双目序列完成原生回放并记录版本、配置、数据哈希和输出；不要立即收集用于概率拟合的正式数据。
3. 依据 B1 第 3—5 节，冻结应用步骤 2 的具体测量契约及六类边界判定。数据/窗口数、h、tau、初始化上限与时序误差阈值目前未冻结；不得标为完成。
4. 实现 B2 的配置和线程生命周期，再进入 B3 的完整建图单元、同步重置/数据库维护；实现顺序不得出现“线程取消了，旧接口还在等”的半可运行状态。B2 运行验收需要的最小同步处理应随模式一起交付，B3 再完成共享单元和全面边界验证。
5. B4 用独立开始/结束时间核对递推，不由输出反算 S；确认无结构性偏差后，才做 B5 三次试运行、插桩开销与轨迹还原，最后开展分布与实用价值比较。

本次补充均保留为工作区改动，未暂存、提交、切换分支或修改远程。已有 AGENTS.md 暂存内容及论文仓库的既有暂存内容保持原状。软件设计与运行证据在本仓库；论文仓库仅增加入口/状态说明，不改理论、历史实验或组会。

## 后续入口（2026-10-17）

用户批准 WSL2 + Ubuntu 22.04，重启后已经完成安装、原生构建及公开序列回放。后续从测量契约开始，B2—B6 尚未实施。实际进度及续接入口见 [wsl-ubuntu-setup.md](wsl-ubuntu-setup.md)，预算见[环境计划](wsl-ubuntu-plan.md)。以上 Windows 配置失败仍保留为历史证据。
