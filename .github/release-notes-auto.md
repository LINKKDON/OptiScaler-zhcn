OptiScaler 简体中文汉化补丁（社区非官方）。

本压缩包是一个**覆盖补丁**，不是完整安装包。解压后把里面的两个文件放进已经在使用的
OptiScaler 安装目录（即上游官方包解压后的那个目录）覆盖同名文件即可：

* `OptiScaler.dll` —— 已注入中文菜单与内嵌 CJK 字体子集
* `OptiScaler.ini` —— 配置项与上游完全一致，只有注释被翻译成中文

覆盖前请先备份原文件。

{{BUILD_TARGET_NOTICE}}

## 上游信息 / upstream information

| 项目 | 值 |
| --- | --- |
| upstream-repository | optiscaler/OptiScaler |
| upstream-version | `{{UPSTREAM_DESCRIBE}}` |
| upstream-sha | `{{UPSTREAM_SHA}}` |
| build-date | {{BUILD_DATE}} |
| artifact | `{{ARCHIVE}}` |

upstream-sha: {{UPSTREAM_SHA}}
upstream-version: {{UPSTREAM_DESCRIBE}}

## 许可证 / License

本产物是 OptiScaler 的衍生作品，OptiScaler 以 GNU General Public License v3.0 发布，
因此本产物同样以 GPL-3.0 发布。按 GPL-3.0 第 6 条，本 Release 同时提供对应源码：

* `corresponding-source.zip` —— 上游 commit `{{UPSTREAM_SHA}}` 的完整源码快照，
  含 `main/`（本仓库之外的 OptiScaler 主仓库）与 `submodules/`（递归子模块各自的源码）
* `submodules.txt` —— 递归子模块在构建开始时记录的版本（`git submodule status --recursive` 原样输出）
* `submodule-shas.txt` —— 实际打进 `corresponding-source.zip` 的每个子模块路径与提交，
  若与上游记录的版本不一致会标注 `(recorded …, checked out …)`
* `upstream-sha.txt` —— 构建时使用的上游 commit

本仓库自身的脚本与工作流同样以 GPL-3.0 发布。
许可证全文：<https://www.gnu.org/licenses/gpl-3.0.txt>

## 字体 / Font

内嵌的中文字体子集取自 Microsoft YaHei（微软雅黑），仅作为本汉化补丁的一部分随附分发，
用于显示中文菜单；本仓库不分发字体文件本身。若你所在地区对该字体的随附分发有额外限制，
请自行替换 `tools_cn/msyh_cjk.ttf` 后重新构建（推荐思源黑体 / Noto Sans CJK 等开源字体）。

## 已知限制

* 只覆盖游戏内主菜单与部分提示文案，overlay 与后端日志文案未翻译完整
* FPS overlay 使用自定义字体时中文可能缺字
* 这是覆盖补丁，必须先有上游官方包
