# 从旧 fork 迁移到瘦仓库

本文记录从 `LINKKDON/OptiScaler`（完整 fork）迁移到 `LINKKDON/OptiScaler-zhcn`（瘦仓库）的原因、方案和步骤。

---

## 一、为什么要迁

旧方案是**完整 fork 上游仓库**，然后在 fork 里提交汉化改动和生成的字体头。运行一段时间后暴露出四个问题，都是结构性的，靠打补丁修不干净。

### 1. fork 落后上游 152 个提交

| | 值 |
| --- | --- |
| fork ahead | 12 个自有提交 |
| fork behind | **152 个上游提交** |
| fork HEAD | `429af9c`（2026-10-26） |
| 仓库体积 | 160 MB |

`sync_upstream.yml` 想用 `git merge --ff-only` 跟上上游。但 fork 上有 12 个自己的提交，`--ff-only` 在存在分叉时**必然失败**——这个工作流从建立起就一直红着，从来没成功同步过一次。想改成 merge/rebase，又会在每次上游大改 `menu/*.cpp` 时产生海量冲突，而汉化的正是这些文件。

结果就是：用户下载到的汉化版，实际是基于一个 152 个提交之前的旧上游。上游修过的 bug、加过的新功能全都没有。

### 2. 仓库里提交了 1.38 MB 的生成物

`OptiScaler/menu/font/CJK_Compressed.h` 是 `build_font.py` 生成的产物：7441 行 C 数组。它被提交进了 git。

这直接导致：

- **clang-format 检查 14/14 全红**。该文件有 7434 行超过 120 字符，最长一行 187 字符。上游的 `.clang-format` 检查配置 `exclude-regex: 'external/|OptiScaler/include/'` 没排除这个路径，于是格式检查把生成物当手写代码判。
- 每次改字典重跑脚本，这个 1.38 MB 文件就整个 diff 一遍，`git log` 被淹没，review 无从下手。
- 仓库体积膨胀，clone 变慢。

生成物本不该进版本库：它完全由 `dict_v10.json` + 字体确定性地推导出来。

### 3. 字体与字典不同步，导致整组菜单显示豆腐块

这是最影响用户的 bug。旧的构建流程里：

- `build_font.py` 读的是旧的 `dict.json`（832 键 → 796 个字符）
- `localize.py` 用的是 `dict_v10.json`（1450 键 → 888 个字符）

两个字典差了 49 个字符：

```
两享仁仍伸候儿充兴勾包句吧哦嘛圆头己干廓心悬截投括断枪柄核欺波王玩班瓶眼睛离窗紧豁豆赶轮辅附顶颈鼠
```

结果这些字在字体子集里根本不存在，运行时渲染成方块。受影响的正是 **Reprojection** 和 **Depth cutoff** 这两整组菜单，几乎没法用。

根因是"生成物入库"：字体头一旦提交，就跟字典脱钩了，字典更新时没人会记得重新生成。

### 4. 汉化零文档

旧仓库的 README 直接是上游的 README 副本，用户完全不知道：

- 汉化了哪些部分、哪些没汉化
- 产物是覆盖补丁还是完整包
- 字体许可、GPL 对应源码在哪
- 遇到问题去哪反馈

---

## 二、新结构

```
LINKKDON/OptiScaler-zhcn        <- 本仓库，只有工具 + 工作流 + 文档
├── .github/workflows/
│   ├── build_zhcn.yml           定时检查上游 + 编译 + 发布（未签名）
│   ├── build_zhcn_signed.yml    手动触发，SignPath 签名后发布
│   └── ci-check.yml             push/PR 时秒级自检
├── tools_cn/
│   ├── build_font.py            字体子集化 + stb 压缩 + 生成字体头
│   ├── localize.py              C++ 字面量替换 + 字体合并代码注入
│   ├── localize_ini.py          ini 注释翻译（绝不碰配置项）
│   ├── dict_v10.json            C++ 字面量字典
│   ├── dict_ini.json            ini 注释字典
│   └── sample_OptiScaler.ini    ci-check 样本
├── README.md  MIGRATION.md  LICENSE  .gitignore
```

关键变化：

| 项目 | 旧 fork | 瘦仓库 |
| --- | --- | --- |
| 上游源码 | 提交进仓库，落后 152 提交 | **不进仓库**，构建时 checkout `optiscaler/OptiScaler@master` 到 `src/` |
| 生成物 `CJK_Compressed.h` | 提交进仓库 1.38 MB | **不进仓库**，每构建现场生成 |
| 同步上游 | `git merge --ff-only`（恒失败） | 天然同步，每次构建都是最新 master |
| clang-format | 14/14 红 | 上游源码格式不受影响（本地化只在 CI 里做，不回写上游仓库） |
| 产物 | 整个 `a/` 目录 | 只有 `OptiScaler.dll` + `OptiScaler.ini` 两个文件 |
| 构造上游版本可追溯 | 无 | Release notes 里有 `upstream-sha` / `upstream-version` |
| GPL 对应源码 | 未提供 | 每个 Release 附 `corresponding-source.zip` + `submodules.txt` |

### 为什么不 fork 了

上游一更新，瘦仓库不需要任何同步动作。汉化逻辑全部是**构建期注入**：拉最新上游 → 生成字体头 → 替换字面量 → 编译 → 发版。上游改了什么代码都不影响本仓库的文件，除非 `OptiScaler/menu/*.cpp` 的字符串结构变了（那时改字典即可）。

### 产物为什么只剩两个文件

旧产物打包整个 `x64\Release\a\*.*`，其中大部分是原样复制过来的上游二进制（`Licenses/`、`setup_windows.bat`、`D3D12_OptiScaler.dll`、各后端 dll 等）。这些本就没变，重复分发只会让用户困惑「哪些该覆盖」。

现在明确它是**覆盖补丁**：只要 `OptiScaler.dll`（汉化）和 `OptiScaler.ini`（只翻注释）。其余文件由用户从上游官方包获取。

---

## 三、迁移步骤

### 1. 创建新仓库

```powershell
# 本地准备好 optiscaler-zhcn/ 目录（本仓库内容）后
git init
git add .
git commit -m "Initial commit: thin repo for the OptiScaler Chinese localization"
git remote add origin https://github.com/LINKKDON/OptiScaler-zhcn.git
git push -u origin main
```

确认 `git status` 里**有** `tools_cn/msyh_cjk.ttf`（551 KB，**必须提交**——它是 `build_font.py` 三级 fallback 的第一级，CI runner 不保证带东亚字体），且**没有** `OptiScaler/`、`CJK_Compressed.h`、`src/`、`x64/`、`*.7z`。

### 2. 归档旧 fork

不要直接删。按顺序：

1. 在旧仓库 `LINKKDON/OptiScaler` 仓库设置里把仓库名改为 `OptiScaler-legacy`（或加 `-archive` 后缀）。**GitHub 会自动重定向旧 URL**，已有链接不会立刻断。
2. 进入 Settings → 底部 **Danger Zone** → **Archive this repository**。归档后只读，`sync_upstream.yml` 不会再跑失败、也不会烧 Actions 分钟数。
3. 在旧仓库 README 顶部加一行醒目提示：

   > ⚠️ 本仓库已归档。新版本与下载请到 [LINKKDON/OptiScaler-zhcn](https://github.com/LINKKDON/OptiScaler-zhcn)。

4. 把旧仓库的 `sync_upstream.yml`、`clang-format` 等会周期性失败的 workflow 停掉（归档本身已让其停止，双保险可 `disable`）。

### 3. 处理旧 Release

旧 Release 的下载数都是 **0**，也没有用户依赖，建议**保留但不更新**：

- 保留：避免已经存在的外部链接 404。
- 在旧 Release notes 顶部补一句「已停止更新，请使用新仓库」。
- 不迁移旧附件：那批产物是基于 152 提交前的上游，且带 49 字符缺失的豆腐块问题，迁过来只会误导用户。
- 如需彻底清理，用 `gh release delete <tag> --yes --cleanup-tag`（在旧仓库目录里执行，或设 `GH_REPO=LINKKDON/OptiScaler`）。

### 4. SignPath 重新绑定

旧 fork 的 SignPath 绑定（organization `d62571e9-818a-4296-bf46-46db55b1a44e`、policy id `08634ea0-3ec2-46df-8a03-755a138a1565`）是**绑定在旧仓库上的**，不会自动跟到新仓库。

1. 登录 SignPath，为 `LINKKDON/OptiScaler-zhcn` 创建/关联 project 与 signing policy。
2. 在新仓库 Settings → Secrets and variables → Actions 添加 `SIGNPATH_API_TOKEN`。
3. 更新 `.github/workflows/build_zhcn_signed.yml` 顶部 `env:` 里的 `SIGNPATH_ORGANIZATION_ID`、`SIGNPATH_PROJECT_SLUG`、`SIGNPATH_POLICY_SLUG`、`SIGNPATH_POLICY_ID`。
4. **重新绑定完成前，签名工作流会失败**。这是刻意的：绝不能静默回退到未签名产物，那样用户会以为拿到的是签名版。

### 5. 迁移后回归检查

在新仓库手动触发一次 `Build Chinese (Auto)`，确认：

- [ ] `build_font.py` 找到字体源（`tools_cn/msyh_cjk.ttf` 或 `C:\Windows\Fonts\msyh.ttc`）
- [ ] 覆盖校验 0 缺字（不应再出现那 49 个字的问题）
- [ ] `localize.py` 输出 `Total keys translated` 非 0
- [ ] `localize_ini.py --check` 通过
- [ ] MSBuild 成功，`src/x64/Release/a/` 里有两个文件
- [ ] `.7z` 里就是平铺的两个文件
- [ ] Release notes 含 `upstream-sha`，附件含 `corresponding-source.zip`、`submodules.txt`
- [ ] 再触发一次（`force` 不勾）—— 应被 skip 逻辑拦住，秒级结束

---

## 四、遗留问题

- **字体许可**：内嵌子集来自 Microsoft YaHei，与 GPL-3.0 公开分发存在法律灰区（字体 name 表 nid=0 含 `© 2024 Microsoft Corporation`、nid=13 有用途限制、OS/2 `fsType = 0x0008` 允许可编辑嵌入）。建议后续换成思源黑体 / Noto Sans CJK（SIL OFL）彻底规避。当前策略是在 README 里明确声明，且不分发字体文件本身。
- **`dict_ini.json` 覆盖上游全部注释**：上游 `OptiScaler.ini` 有 902 条注释行、696 个唯一 key，字典已全部收录；上游若新增注释，未命中的行会原样保留英文，`--report` 可统计未命中数，`--lint-dict` 可反向检查字典里有没有已经过时的 key。
- **`std::format` 动态拼接文案**：字典无法整串匹配，这部分永远翻不到。要彻底解决需要改上游代码引入 `tr()` 类接口，属于上游的事。
- **版本号来源容错**：上游不同快照的 `resource.h` 位置/是否存在不一致，工作流找不到那四个宏时会退回用 `git describe` 派生的文件名并打 `::warning::`，不会卡死构建。
