<p align="center">
  <img src="src/re_sputnik/resources/branding/banner_zh.png" alt="Re:Sputnik" width="760">
</p>

<p align="center">
  <a href="https://t.me/one_andrevich"><img src="https://img.shields.io/badge/Telegram-Join-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
  <a href="https://ko-fi.com/D1D11SQNQD"><img src="https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white" alt="Ko-fi"></a>
  <a href="https://nowpayments.io/donation?api_key=decbeb76-30f8-4c6d-ba40-2d2dec7fd888"><img src="https://img.shields.io/badge/Crypto-Donate-2EBE74?style=flat-square&logo=bitcoin&logoColor=white" alt="Crypto donate"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue?style=flat-square" alt="License: GPL-3.0"></a>
</p>

# Re:Sputnik

[English](README.md) · [Русский](README_ru.md) · [فارسی](README_fa.md) · **中文**

> ⚠️ **本文为机器翻译。** 以英文 README 为准；欢迎指正。

**桌面应用，通过 SSH 在 OpenWrt 路由器上安装和管理 [Re:HomeProxy](https://github.com/1andrevich/homeproxy-hiddify)——无需使用终端或 LuCI。**

你只需输入路由器的地址和密码；其余工作由应用在图形向导中完成：安装代理后端和内核，导入你的服务器，
设置路由和 DPI 绕过，之后还可管理 Wi-Fi、诊断与安全。

> Re:Sputnik **不**捆绑任何代理内核——它从官方来源将其安装到路由器上，并且仅通过 SSH/RPC 与路由器
> 通信（`ubus call luci.homeproxy.*`、`uci`、软件包自带的脚本）。其本质是一个通用的「在 OpenWrt 上
> 安装 + 配置软件」平台；Re:HomeProxy 只是第一个方案。

## 下载

从 [**Releases**](https://github.com/1andrevich/re-sputnik/releases) 页面获取最新构建——无需安装程序。需要路由器运行 **OpenWrt 23.05 或更高版本**。

- **Windows** —— `Re-Sputnik-windows-x64.exe`，双击运行。
- **macOS**（Apple Silicon）—— `Re-Sputnik-macos-arm64.zip`，解压后将 `Re-Sputnik.app` 拖入 Applications。
- **Linux** —— `Re-Sputnik-linux-x86_64.AppImage` / `-aarch64.AppImage`，`chmod +x` 后运行。

当前构建**未签名**。Windows SmartScreen 会警告（More info → Run anyway）。在 macOS 上首次启动会被
拦截——打开**系统设置 → 隐私与安全性**，滚动到**安全性**部分，点击 Re-Sputnik 旁边的**仍要打开**
（用 Touch ID / 密码确认）。只需一次。

## 功能

- **安装** —— 检测路由器的架构和包管理器（opkg/apk），安装 Re:HomeProxy 和一个代理内核
  （**hiddify-core** 或 **sing-box-extended**），并可在电脑上预先下载软件包，供处于限速/受限网络的
  路由器使用。
- **服务器** —— 导入订阅（sing-box/Hiddify JSON 和 Xray/V2Ray JSON）、分享链接（VLESS/Reality、
  Hysteria2、Trojan、Shadowsocks…）、`vpn://` 以及 `.conf` 文件（WireGuard/AmneziaWG）；URLTest
  测速分组。
- **路由** —— 基于 Re:filter 和 Russia Inside 规则集的预设模式（俄罗斯 / 中国 / 伊朗 / 全局）。
- **DPI 绕过** —— 内置 **ByeDPI**（47 个预设）和 **Zapret 2**（36 个预设），以及一个策略测试器，
  并行探测多个站点，显示在你的 ISP 上实际有效的方案。
- **管理** —— 诊断（内核状态、DNS、路由）、Wi-Fi / LAN / DHCP、密码和 SSH 密钥、备份与维护、
  SQM / UPnP。
- **语言** —— 俄语、英语、波斯语、中文。可保存多个路由器配置。

## 三种入口

- **⚡ 分步向导** —— 线性向导，引导非技术用户完成联网、安装、服务器和验证。
- **⚙ 高级** —— 在各模块间自由导航（服务器、规则、诊断、Anti-DPI、内核、安全…）进行手动管理。
- **📦 预装软件包** —— 在电脑上下载并推送到路由器，以便在路由器本身没有网络的情况下安装。

任何模式都会沿用路由器的当前配置，而不是从零开始。

## 架构（简述）

```
UI (customtkinter)          向导与设置界面；驱动配置流程
engine/*                    各功能的逻辑（安装、节点、规则、ByeDPI、Zapret、诊断…）
RouterClient (paramiko)     通往路由器的唯一入口：内置脚本、ubus、uci
Secrets (keyring)           路由器凭据存于操作系统密钥链
```

每个连接上的命令逐条执行，因此并发请求不会被路由器的 SSH 守护进程丢弃。无遥测、无统计分析：应用仅与
你连接的路由器、你提供的订阅/更新 URL，以及安装软件时使用的官方软件源（GitHub、OpenWrt）通信。
凭据绝不离开你的设备。

## 技术栈

纯 Python + 少量库——无 web/HTML/CSS/JS：

| 层 | 库 |
|----|----|
| 界面 | customtkinter (Tk) |
| 路由器通信 | paramiko (SSH) |
| 凭据 | keyring（操作系统密钥链） |
| 图标 | Lucide/Phosphor（界面）+ Simple Icons（品牌），构建时 SVG→PNG |

## 开发

```sh
python -m venv .venv
. .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m re_sputnik
python -m compileall -q src && pytest -q
```

CI 在每次 push 时运行测试（[`test.yml`](.github/workflows/test.yml)）；按需的多平台构建在
[`build.yml`](.github/workflows/build.yml)；带标签的发布（`vX.Y.Z`）会构建所有平台并通过
[`release.yml`](.github/workflows/release.yml) 发布到 Releases 页面。贡献流程见
[`CONTRIBUTING.md`](CONTRIBUTING.md)（Developer Certificate of Origin）。

## 商标声明

与 YouTube、Telegram、Discord、Meta 或 Hiddify 无关联，也未获其背书。服务徽标为各自所有者的商标，
仅用于标识相应服务。

## 支持项目

如果 Re:Sputnik 对你有帮助，点个 ⭐ 就很好——也可以直接支持开发：

<a href="https://ko-fi.com/D1D11SQNQD" target="_blank"><img height="40" src="https://storage.ko-fi.com/cdn/kofi5.png?v=6" alt="在 Ko-fi 上支持"></a>
&nbsp;
<a href="https://nowpayments.io/donation?api_key=decbeb76-30f8-4c6d-ba40-2d2dec7fd888" target="_blank" rel="noreferrer noopener"><img src="https://nowpayments.io/images/embeds/donation-button-white.svg" alt="通过 NOWPayments 进行加密货币和比特币捐赠"></a>

问题与更新 —— [Telegram](https://t.me/one_andrevich)。

## 许可证

Re:Sputnik 是基于 **GNU General Public License v3.0**（GPLv3）的**自由软件**：你可以在该条款下
使用、研究、修改和分享它。完整文本见 [`LICENSE`](LICENSE)，第三方署名见 [`NOTICE`](NOTICE)。

Re:Sputnik 是独立于 **Re:HomeProxy**（同为 GPL 许可）的程序：它通过 SSH/RPC 与路由器通信，不捆绑或
链接 Re:HomeProxy 的源代码。所有捆绑的第三方依赖均采用宽松或弱 copyleft 许可证（MIT/BSD/HPND/
MPL-2.0；paramiko 为 LGPL-2.1），与 GPLv3 兼容。贡献依据 Developer Certificate of Origin 接受——见
[`CONTRIBUTING.md`](CONTRIBUTING.md)。
