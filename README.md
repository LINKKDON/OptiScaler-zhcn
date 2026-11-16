# OptiScaler 简体中文汉化

给 [OptiScaler](https://github.com/optiscaler/OptiScaler) 的游戏内菜单加上简体中文的**社区汉化补丁**（Windows）。

> **本项目是非官方汉化，与 OptiScaler 上游作者无关，也不是一个 fork。**
> 本仓库里没有一行上游源码，只放汉化工具脚本、GitHub Actions 工作流和文档。

---

## 这个补丁是什么

一个**覆盖补丁**，不是完整安装包。每个 Release 的 `.7z` 里只有两个文件，平铺在压缩包根目录：

| 文件 | 说明 |
| --- | --- |
| `OptiScaler.dll` | 汉化后重新编译的主文件，内嵌了中文字体子集，运行时把菜单字体合并进去 |
| `OptiScaler.ini` | 配置文件。**配置项与上游完全一致**，只有注释被翻译成中文 |

用法：先把上游官方包解压到游戏目录，再用本补丁里的这两个文件覆盖同名文件。

```
<游戏目录>/
  OptiScaler.dll      <- 用本补丁的覆盖
  OptiScaler.ini      <- 用本补丁的覆盖
  ...
```

覆盖前请备份原文件，想回退时换回来即可。

---

## 下载

到 [Releases](../../releases) 页面挑最新一个带 `zh-cn-` 前缀的版本，下载 `.7z`。

每个 Release 有两个版本：

- `zh-cn-OptiScaler_...` —— 未签名（`Build Chinese (Auto)` 产出）
- `zh-cn-signed-OptiScaler_...` —— 已过 SignPath 签名（`Build Chinese (Signed)` 手动触发）

两个前缀刻意不重叠：`skip` 判定用 `zh-cn-OptiScaler_*` 精确匹配，避免签名版发布后无签名 workflow 误以为同一 commit 已发布而跳过。

**签名版说明**：用的是 SignPath 的**自签名测试证书**，Windows 会显示「未知发布者」，SmartScreen 也可能拦一下。这是预期行为，不是文件损坏。

每个 Release 还附带 GPL-3.0 要求的对应源码（见下方「许可证」）。

---

## 与上游的关系

```
optiscaler/OptiScaler   （上游，GPL-3.0，本仓库的构建输入）
        │
        │  CI 构建时 checkout 到子目录 src/，注入汉化后编译
        ▼
LINKKDON/OptiScaler-zhcn （本仓库：只有 tools_cn/ + .github/workflows/ + 文档）
        │
        └──► Release 附件：OptiScaler.dll + OptiScaler.ini (+ 对应源码)
```

也就是说：

- 上游源码**不进**本仓库。每次构建都由 CI 拉 `optiscaler/OptiScaler@master` 到 `src/`。
- 汉化是**构建期注入**的：`build_font.py` 生成字体头，`localize.py` 替换 `OptiScaler/menu/*.cpp` 里的英文字面量并插入字体合并代码，`localize_ini.py` 翻译 `OptiScaler.ini` 的注释。
- 因此上游一更新，本仓库不需要同步任何源码，重新跑一次工作流即可。

---

## 本地构建

### 依赖

- Windows 10/11 x64
- Visual Studio 2022，装「使用 C++ 的桌面开发」工作负载（需要 MSVC v143 与 Windows SDK）
- Python 3.10+
- 7-Zip（`7z` 在 `PATH` 里）
- 中文字体：`tools_cn/msyh_cjk.ttf` **已随仓库提交**（551 KB 子集），无需额外准备。若它缺失，`build_font.py` 才会退回系统字体 `C:\Windows\Fonts\msyh.ttc`（本地开发机通常有，但 CI runner 不保证有）。

`build_font.py` 的字体查找顺序是三级 fallback：

1. `tools_cn/msyh_cjk.ttf`（**仓库内已提供，这是 CI 走的路径**）
2. `C:\Windows\Fonts\msyh.ttc`（本地开发兜底）
3. 都没有 → 报错并提示怎么生成 `msyh_cjk.ttf`

第 1 级存在的意义就是不让构建依赖 runner 的系统字体：`windows-latest` 不保证安装东亚字体包，微软雅黑在 Windows Server 上是可选组件，所以**不要把 `tools_cn/msyh_cjk.ttf` 加进 `.gitignore`**。

替换成自己的字体（例如思源黑体）后重新生成这个子集：

```powershell
python tools_cn/build_font.py --source C:\Windows\Fonts\msyh.ttc --ttf-out tools_cn/msyh_cjk.ttf
```

### 步骤

```powershell
# 0) 准备
python -m pip install fonttools

# 1) 取上游源码到 src/
git clone --depth 1 --recurse-submodules https://github.com/optiscaler/OptiScaler.git src

# 2) 生成内嵌字体头 -> src/OptiScaler/menu/font/CJK_Compressed.h
python tools_cn/build_font.py --out src/OptiScaler/menu/font --source C:\Windows\Fonts\msyh.ttc

# 3) 注入汉化字面量与字体合并代码
python tools_cn/localize.py --repo src --tools tools_cn

# 4) 汉化 ini 注释
python tools_cn/localize_ini.py --ini src/OptiScaler.ini --dict tools_cn/dict_ini.json --out src/OptiScaler.ini --report

# 5) 编译
msbuild src/OptiScaler.sln /m /p:Configuration=Release /verbosity:minimal

# 6) 打包（只用两个文件）
7z a OptiScaler-zhcn_local.7z .\src\x64\Release\a\OptiScaler.dll .\src\x64\Release\a\OptiScaler.ini
```

`localize.py` 与 `localize_ini.py` 都是**幂等**的，重复跑不会叠加改动（第二次 `Total keys translated` 应为 0）。

### 工具自检

```powershell
python tools_cn/build_font.py --selftest          # stb_compress/stb_decompress 往返测试（9 种尺寸）
python tools_cn/build_font.py --check             # 只做字典字符覆盖校验，缺字打印码位并返回 1
python tools_cn/localize.py --check-dict --tools tools_cn
python tools_cn/localize_ini.py --ini tools_cn/sample_OptiScaler.ini --check
python tools_cn/localize_ini.py --ini <上游 OptiScaler.ini> --report    # 还有多少注释未译
python tools_cn/localize_ini.py --ini <上游 OptiScaler.ini> --lint-dict # 字典里有没有多余/过期键
```

补充两条约定：

- `--check-dict` 对「大小写近重复键」只报警告。`dict_v10.json` 是从上游原样搬来的，里面确实有 `ON`/`On`、`OFF`/`Off`、`Auto Exposure`/`Auto exposure` 这类成对条目（对应不同上下文）。想把它们也判成错误，加 `--strict-case-dup`。
- `localize_ini.py --lint-dict` 要求字典里的每个键都能在传入的 ini 里找到，所以**不进 CI**（仓库里只有 20 行的 `sample_OptiScaler.ini`，696 个键会全被判缺失）。它是发布前的手工命令。

---

## 工作流

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| `build_zhcn.yml` (`Build Chinese (Auto)`) | 每天 06:00 UTC 定时；也可手动 dispatch（`force` 勾上则强制重建） | 检查上游是否更新；有更新就编译并发布未签名 Release |
| `build_zhcn_signed.yml` (`Build Chinese (Signed)`) | 仅手动 dispatch | 同上去加 SignPath 签名，发布签名版 Release |
| `ci-check.yml` (`CI`) | 本仓库 push / PR | 秒级自检：py_compile、stb 往返、字典校验、ini 校验、YAML 可解析、无 BOM/CRLF/tab |

`ci-check.yml` 共 10 步，最后一步只扫本仓库真正发布的路径（`tools_cn/`、`.github/`、`README.md`、`MIGRATION.md`、`LICENSE`、`.gitignore`、`.gitattributes`），不去扫本机的临时工作目录。

仓库带 `.gitattributes`（`* text=auto eol=lf`，二进制扩展名标 `binary`），`*.py` / `*.json` / `*.yml` / `*.md` 一律存 LF。就算有人在 CRLF 工作区提交，git 也会在入库时归一化——但别指望它兜底，最后那步扫描才是真正的防线。

**为什么没有 push 触发构建**：改文档、改字典不该触发一次 90 分钟的编译。定时任务会先比对上游 commit，如果 `OptiScaler.dll` 对应的 `upstream-sha` 已经发过 Release 就直接跳过（`skip` 输出 + Step Summary 说明）。

**`submodules: recursive` 的代价**：上游 `.gitmodules` 声明的子模块合计约 1.49 GB（`intel/xess` ≈660 MB、`FidelityFX-SDK` ≈554 MB、`nvapi` ≈120 MB、`Vulkan-Headers` ≈92 MB，其余几个都很小），每次构建都要重新拉一遍。**两个工作流都刻意没有挂 `actions/cache`**：缓存 `src/.git/modules` 看起来能省掉这 1.49 GB，但 `actions/checkout` 的 `prepareExistingDirectory()` 在目标路径存在 `.git` 却没有可用的 `remote.origin.url` 时会把目录内容整个删掉，而缓存的 `modules/` 里没有 `.git/config` —— 恢复出来的对象随即被清空。键又是按 `run_id` 生成的，永远命不中确切条目，于是每次运行都要在收尾时上传约 1.5 GB 却从不复用，比不缓存更糟。真要缓存得改成 `submodules: false` + 手动 `git submodule update --init --recursive`，那会引入一个只能在真实 runner 上验证的新失败点，暂时不做。子模块参与链接，也不能砍。

**`GH_REPO` 为什么到处都是**：构建时工作目录里同时存在 `self/`（本仓库）和 `src/`（上游）两份 git 仓库，`gh` 会猜错仓库。所有 `gh` 调用都显式设 `env: GH_REPO: ${{ github.repository }}`。同理，删旧 tag 一律走 `gh release delete <tag> --yes --cleanup-tag`，从不用 git 侧的 tag 删除命令——那会以当前工作目录的仓库为前提，指向错误的仓库。

### 需要的 secret

| 名称 | 用于 | 说明 |
| --- | --- | --- |
| `SIGNPATH_API_TOKEN` | `build_zhcn_signed.yml` | SignPath API token。未配置时签名版工作流会直接失败（有意为之） |

`build_zhcn.yml` 只需要默认的 `GITHUB_TOKEN`（`permissions: contents: write`）。

> **SignPath 需要在新仓库重新绑定**：工作流里的 `SIGNPATH_ORGANIZATION_ID`（`d62571e9-...`）、`SIGNPATH_PROJECT_SLUG`、`SIGNPATH_POLICY_SLUG`、`SIGNPATH_POLICY_ID`（`08634ea0-...`）都是从旧 fork 沿用的值。迁移到本仓库后必须在 SignPath 后台重新绑定项目/策略，并同步改 `.github/workflows/build_zhcn_signed.yml` 顶部的 `env:` 块。**在那之前签名版会失败——这是刻意的，绝不静默发布未签名产物。**

> **Artifact Configuration 要按 ZIP 配**：`actions/upload-artifact@v4` 无论上传单个文件还是目录，产出都是一个 ZIP。工作流没有设 `archive: false`（v4 也不支持该选项），所以 SignPath 后台的 Artifact Configuration 根元素必须是 `<zip-file>`，里面再定位 `<pe-file>` 的 `OptiScaler.dll`。配成裸 `<pe-file>` 会在提交阶段就报找不到文件。这一项只能在 SignPath 后台确认，本仓库改不了。

---

## 目录结构

```
.github/workflows/
  build_zhcn.yml           未签名构建 + 发布
  build_zhcn_signed.yml    签名构建 + 发布
  ci-check.yml             本仓库自检
.github/
  release-notes-auto.md    Release 说明模板（未签名版）
  release-notes-signed.md  Release 说明模板（签名版）
tools_cn/
  build_font.py            子集化字体 -> stb 压缩 -> 生成 CJK_Compressed.h
  localize.py              替换 C++ 里的 UI 字面量 + 插入字体合并代码
  localize_ini.py          只翻译 OptiScaler.ini 的注释行
  render_notes.py          用环境变量填充 Release 说明模板
  dict_v10.json            C++ 字面量字典（1450 条）
  dict_ini.json            ini 注释字典
  sample_OptiScaler.ini    ci-check 用的小样本
  msyh_cjk.ttf             已提交的字体子集（551 KB，920 码位），CI 的第一级字体源
```

Release 说明是模板 + 环境变量填出来的（`render_notes.py`）：模板里的 `{{UPSTREAM_SHA}}` 等占位符必须全部被替换，残留一个就构建失败。`gh release list` 的跳过判定读的就是渲染结果里的 `upstream-sha:` 那一行。

---

## 许可证

### 本仓库

本仓库的脚本、工作流与文档以 **GNU General Public License v3.0** 发布，与上游保持一致。
许可证全文见 [LICENSE](LICENSE) 或 <https://www.gnu.org/licenses/gpl-3.0.txt>。

### 产物

`OptiScaler` 本身以 GPL-3.0 发布，**它的版权归上游作者所有**。本仓库产出的 `OptiScaler.dll` 是上游源码的衍生作品，因此同样以 GPL-3.0 发布。

按 GPL-3.0 第 6 条（对应源码的提供义务），**每个 Release 都同时附上**：

- `corresponding-source.zip` —— 构建所用上游 commit 的完整源码快照，`main/` 是 OptiScaler 主仓库，`submodules/` 是每个递归子模块各自的源码树
- `submodules.txt` —— 递归子模块在构建开始时记录的版本（`git submodule status --recursive` 原样输出）
- `submodule-shas.txt` —— 实际打进压缩包的每个子模块路径与提交；与上游记录的版本不一致时会标注 `(recorded …, checked out …)`
- `upstream-sha.txt` —— 构建时使用的上游 commit

本仓库只提供汉化补丁，**不主张对上游作品的任何额外权利**。

---

## 字体许可提示

内嵌进 `OptiScaler.dll` 的中文字体子集来自 **Microsoft YaHei（微软雅黑）**，仅作为本汉化补丁的一部分随附分发，用于显示中文菜单。

- **仓库里只保存 920 码位的子集**（`tools_cn/msyh_cjk.ttf`，≈551 KB），**不保存原始的 `C:\Windows\Fonts\msyh.ttc`**（那个有 29905 码位、体积大，且其内嵌许可不随文件转移）。
- 编译期再把这份子集二次子集化并 stb 压缩后塞进 `CJK_Compressed.h`（约 477 KB），因此 Release 分发的是**补丁产物**，不是可用字体。
- 子集内保留的 name 表信息仍指向微软雅黑（雅黑 `OS/2 fsType = 0x0008`，允许可编辑嵌入）。**若你所在地区对随附分发有额外限制，请自行替换字体后重新构建**：把开源字体（推荐**思源黑体 / Noto Sans CJK**，SIL OFL）作为 `--source` 重新生成子集即可：

  ```powershell
  python tools_cn/build_font.py --source C:\path\to\SourceHanSans.ttc --ttf-out tools_cn/msyh_cjk.ttf
  ```

---

## 已知限制

- **只覆盖主菜单**：`OptiScaler/menu/*.cpp` 里的 UI 字面量。overlay 提示、后端日志等文案未翻译。
- **约 75% 的有效覆盖**：`std::format` 动态拼接出来的字符串（如 `std::format("{} Doesn't support more than {}x", ...)`）无法整串匹配，这类条目在字典里命中不到。
- **`OptiScaler.ini` 只翻注释**：配置项（`key`、`[Section]`、取值）一律不动。注释字典 `tools_cn/dict_ini.json` 当前覆盖上游全部 902 条注释（696 个唯一 key），`--report` 会显示 `not in dictionary` 为 0；上游新增注释后未命中的行原样保留英文，用 `--report` 可以看未命中数。
- **FPS overlay 缺字**：如果游戏或用户自定义了 overlay 字体，中文字符不在那个字体里，会显示成方块。内置字体子集只保证本补丁自己创建的字体 atlas 里有字。
- **只支持 Windows x64**：构建产物是 `Release|x64`。
- **产物是覆盖补丁**：不能单独使用，必须先有上游官方包。

---

## 相关

- 上游项目：<https://github.com/optiscaler/OptiScaler>
- 从旧 fork 迁移过来的说明：[MIGRATION.md](MIGRATION.md)
- GPL-3.0 全文：<https://www.gnu.org/licenses/gpl-3.0.txt>
