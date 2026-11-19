OptiScaler 简体中文汉化补丁（社区非官方，**已签名**版本）。

本压缩包是一个**覆盖补丁**，不是完整安装包。解压后把里面的两个文件放进已经在使用的
OptiScaler 安装目录（即上游官方包解压后的那个目录）覆盖同名文件即可：

* `OptiScaler.dll` —— 已注入中文菜单与内嵌 CJK 字体子集，并已用自签名证书签名
* `OptiScaler.ini` —— 配置项与上游完全一致，只有注释被翻译成中文

覆盖前请先备份原文件。

> **签名说明**：本产物使用构建流水线内**即时生成的自签名代码签名证书**
> （`CN=OptiScaler-zhcn (community build)`，有效期 2 年，仅用于本次构建，不对外提供私钥）。
> Windows 会显示「未知发布者」，SmartScreen 也可能拦截 —— 这是自签名证书的预期行为，
> 不是文件损坏。若要确认文件完整性，请核对 Release 里的 SHA256，或用
> `Get-AuthenticodeSignature` 查看签名者。如需受信任的签名，可自行用 `signtool` 重签，
> 或改用未签名的 `zh-cn-OptiScaler_*` 版本。

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

## 汉化覆盖率 / translation coverage

{{COVERAGE}}

这是「本版字典还能命中上游多少条可译字面量」的实测值。上游改动菜单措辞后，未跟进的
条目会退回英文，所以这个数字会随上游漂移；构建脚本会在它相对基线一次掉超过 20 条时
直接失败，掉 1–20 条时只报警。

## 签名 / Signature

| 项目 | 值 |
| --- | --- |
| 证书 | 构建期自签名，`CN=OptiScaler-zhcn (community build)` |
| 用途 | Code Signing（`1.3.6.1.5.5.7.3.3`），Digital Signature |
| 有效期 | 2 年（自本次构建起算） |
| 私钥 | 仅存在于本次构建的 runner 上，构建结束即销毁 |

签名步骤在 `build_zhcn_signed.yml` 里用 `New-SelfSignedCertificate` + `Export-PfxCertificate`
生成证书，再用 Windows SDK 自带的 `signtool.exe` 签名，最后用 `Get-AuthenticodeSignature`
断言签名确实存在（`Status` 不得为 `NotSigned`，`SignerCertificate` 不得为空）。
`NotTrusted` 是自签名证书在未安装该证书的机器上的预期状态，不判为失败。

## 许可证 / License

本产物是 OptiScaler 的衍生作品，OptiScaler 以 GNU General Public License v3.0 发布，
因此本产物同样以 GPL-3.0 发布。按 GPL-3.0 第 6 条，本 Release 同时提供对应源码的**指针**：

* `SOURCE.md` —— 说明如何用下面的 commit 与补丁重建本包的确切源码树（含 9 个子模块的
  仓库地址与提交），并列出汉化补丁涉及的文件
* `overlay.patch` —— 从上游 commit 到本包构建所用源码树的完整 diff（`git diff --binary`），
  在上游 commit 的检出上 `git apply --binary` 即可复现
* `submodules.txt` —— 递归子模块在构建开始时记录的版本（`git submodule status --recursive` 原样输出）
* `submodule-shas.txt` —— 实际参与构建的每个子模块路径与提交，
  若与上游记录的版本不一致会标注 `(recorded …, checked out …)`
* `upstream-sha.txt` —— 构建时使用的上游 commit

之所以用指针而不是随包附带完整源码快照：本包的全部输入都是公开、不可变的 git 对象，
按 commit + 补丁即可逐字节复现；而完整快照有 565 MB，其中约 500 MB 是两个 FidelityFX SDK
子模块里的预编译 DLL 与文档，它们并不参与编译。若将来某个 commit 变得不可达，会改回随包
附带完整快照。

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
