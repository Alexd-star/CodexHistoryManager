# Codex History Manager

![Windows](https://img.shields.io/badge/Windows-Desktop-2563eb)
![Python](https://img.shields.io/badge/Python-3.11+-3776ab)
![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-0f766e)
![License](https://img.shields.io/badge/License-MIT-111827)

一个面向 Windows 的 Codex 本地对话历史管理器，用于查看、搜索、恢复、归档、导出和备份本机 `.codex` 会话记录。

它的目标不是替代 Codex，而是补上“本地历史可管理、可恢复、可导出、可备份”的工具层：当侧边栏记录缺失、排序异常、标题不准确，或者需要把某段历史整理成 Markdown / HTML / JSON 时，可以用这个工具快速处理。

当前版本：`0.1.3`

## 核心能力

- **会话列表管理**：读取 `state_5.sqlite`、`session_index.jsonl`、`sessions` 与 `archived_sessions`。
- **本地历史恢复**：根据 JSONL 文件尾部最后一条消息/事件修复 Codex 会话索引与更新时间排序。
- **清晰预览阅读**：用高速阅读器按角色、时间、轮次 ID 和图片数量展示会话内容。
- **全文搜索**：可在用户、助手、开发者、系统消息中搜索关键词。
- **归档与恢复**：通过 SQLite 状态标记管理会话，不移动原始 JSONL 文件。
- **批量处理**：支持多选后批量导出、备份、归档、恢复和恢复最新。
- **多格式导出**：支持 Markdown、HTML、TXT、JSON，支持分会话文件或合集。
- **图片提取**：导出时可将 data URL 图片提取到 `images/` 目录。
- **内容筛选**：导出可按角色、关键词、日期范围和内容类型过滤。
- **安全备份**：写操作前自动备份状态数据库、索引文件和目标会话文件。
- **诊断中心**：显示路径、状态、最近备份、最近操作，可一键复制诊断信息。
- **客户反馈包**：一键打包诊断信息、日志尾部和操作元数据，不包含聊天正文。
- **检查更新**：可从桌面端检查 GitHub Releases 最新版本，并打开下载页面。
- **客户级数据目录**：导出、备份、日志默认写入用户本地数据目录，不依赖 EXE 所在位置。
- **配置持久化**：用户选择 Codex 数据目录后会自动记住，下次启动继续使用。
- **备用 Web 端**：桌面版可手动启动/停止本机 Web 服务，方便浏览器临时查看。

## 适合谁使用

- 经常使用 Codex，需要长期保存和复查本地对话记录的人。
- 需要把 Codex 会话整理成 Markdown 文档、HTML 页面或 JSON 数据的人。
- 遇到 Codex 历史记录顺序不对、标题异常、侧边栏记录消失等问题的人。
- 希望在不上传云端、不暴露隐私的前提下管理本地 AI 开发记录的人。

## 界面特性

- 桌面版 EXE 优先，双击即可运行。
- 启动默认屏幕居中。
- 会话列表使用主题图案徽标、状态标签、更新时间和文件大小标签。
- 搜索、筛选、预览、导出、管理分区清晰。
- 管理页提供诊断中心，可打开导出目录、备份目录和日志目录。
- 预览正文会自动处理超长行、路径、命令和日志文本，避免内容挤成一行。
- 超长消息会在预览中折叠，完整内容可通过导出查看。

## 性能优化

为保证大量历史记录下仍然流畅，本项目做了多处性能处理：

- 列表分批渲染，避免一次性创建大量控件导致界面卡顿。
- 普通筛选使用预计算搜索索引，不重复拼接标题、路径和预览文本。
- 点选会话只更新上一行和当前行高亮，不重建整个列表。
- 勾选、全选、清空只刷新必要行。
- 快速切换会话时预览加载自动防抖，只加载最后停留的会话。
- 旧预览请求会被丢弃，防止旧内容覆盖新内容。
- 最近消息读取使用文件尾部读取，避免大会话每次预览都扫描完整 JSONL。
- 超长消息预览先限量再排版，避免单条巨大日志拖慢界面。

## 项目结构

```text
CodexHistoryManager/
├─ app.py                    # 核心数据逻辑、本地 API、导出、备份、索引修复
├─ modern_app.py             # 现代桌面版主程序，当前 EXE 打包入口
├─ desktop_app.py            # 早期桌面界面，保留用于对照
├─ static/index.html         # 备用 Web 管理界面
├─ assets/                   # 应用图标和界面资源
├─ tests/冒烟测试.py          # 基础功能测试
├─ docs/设计说明.md           # 设计说明
├─ 打包桌面版EXE.ps1          # PyInstaller 打包脚本
├─ 启动Codex历史管理器.ps1     # 备用 Web 版启动脚本
└─ 启动Codex历史管理器.cmd     # 备用 Web 版双击启动入口
```

运行过程中会生成以下用户数据目录。发布版 EXE 可以放在任意位置，导出、备份、日志不会写到 EXE 所在目录：

```text
%LOCALAPPDATA%\CodexHistoryManager\
├─ exports\       # 导出结果
├─ backups\       # 写操作前备份
├─ logs\          # 操作日志和应用日志
└─ config.json    # 用户选择的数据目录等配置
```

源码开发时仍会产生 `build/`、`dist/`、`__pycache__/` 等构建目录，这些目录默认不会提交到 Git。

## 快速开始

### 方式一：下载发布版安装包

进入 GitHub Releases 页面下载：

```text
https://github.com/Alexd-star/CodexHistoryManager/releases
```

推荐普通用户下载 `CodexHistoryManager-Setup-v版本号.exe`。安装包会安装到当前用户目录，创建开始菜单快捷方式，并支持从 Windows 设置中卸载。

也可以下载 `CodexHistoryManager.exe` 作为绿色版单文件程序，双击即可运行。

### 方式二：从源码运行

#### 1. 克隆项目

```powershell
git clone https://github.com/Alexd-star/CodexHistoryManager.git
cd CodexHistoryManager
```

#### 2. 安装依赖

建议使用 Python 3.11 或更高版本。

```powershell
python -m pip install -r requirements.txt
```

#### 3. 启动桌面版

```powershell
python .\modern_app.py
```

程序会默认读取当前用户目录下的：

```text
C:\Users\<用户名>\.codex
```

也可以在界面中点击“选择数据目录”，手动选择其他 Codex 数据目录。
选择后会写入 `%LOCALAPPDATA%\CodexHistoryManager\config.json`，下次启动自动使用上次选择的目录。

#### 4. 打包 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\打包桌面版EXE.ps1
```

生成文件：

```text
dist\CodexHistoryManager.exe
```

#### 5. 打包安装包

安装包使用 Inno Setup 6 生成。如果本机没有安装 Inno Setup，可以先运行：

```powershell
winget install --id JRSoftware.InnoSetup -e --silent
```

然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\打包安装包.ps1
```

生成文件：

```text
dist\CodexHistoryManager-Setup-v版本号.exe
```

#### 6. 启动备用 Web 版

桌面版中可以手动启动 Web 服务，也可以直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\启动Codex历史管理器.ps1
```

默认访问：

```text
http://127.0.0.1:8765
```

Web 服务只绑定 `127.0.0.1`，默认仅本机可访问。

## 使用方式

### 恢复最新记录

1. 在会话列表中选择一个或多个会话。
2. 点击“恢复当前最新”或“恢复选中最新”。
3. 程序会先自动备份，再根据 JSONL 中最后一条消息/事件修复索引。

适用于：

- Codex 侧边栏排序不是最新。
- 会话标题或更新时间异常。
- 本地 JSONL 文件存在，但界面记录不完整。

### 导出会话

支持以下格式：

- Markdown
- HTML
- TXT
- JSON

支持以下筛选：

- 用户消息
- 助手消息
- 开发者消息
- 系统消息
- 关键词
- 日期范围
- 图片附件
- 工具调用轨迹
- 运行事件

### 归档与恢复

归档/恢复仅修改 Codex 状态数据库中的归档标记，不移动原始 JSONL 文件。每次写操作前都会生成备份。

### 诊断中心

管理页提供“诊断中心”，用于排查路径、权限、备份、导出和会话扫描问题。

诊断中心支持：

- 刷新诊断信息；
- 复制诊断信息；
- 打开导出目录；
- 打开备份目录；
- 打开日志目录；
- 查看最近备份和最近操作。

如果操作失败，程序会把异常堆栈写入 `logs/应用日志.log`。发送诊断信息给他人前，请确认其中没有你不想公开的本地路径。
发布版日志默认位于 `%LOCALAPPDATA%\CodexHistoryManager\logs\应用日志.log`。

### 客户反馈包

管理页提供“生成反馈包”。反馈包用于售后排查，默认保存到导出目录，内容包括：

- 诊断信息；
- 最近操作记录；
- 应用日志尾部；
- 操作日志尾部；
- 反馈包说明。

反馈包不包含 Codex 会话正文，也不包含 `sessions` 或 `archived_sessions` 下的原始 JSONL 聊天文件。它可能包含本机路径、用户名、版本号和目录状态，发送给他人前请确认这些路径信息可以公开。

### 检查更新

管理页提供“检查更新”。程序会访问 GitHub Releases 最新版本接口，仅用于比较当前版本和最新版本。网络不可用时不会影响本地历史管理功能。

## 安全说明

本项目默认保护本地隐私：

- 不上传 `.codex` 原始数据。
- 不删除 Codex 原始会话文件。
- 不移动 `sessions` 和 `archived_sessions` 中的 JSONL 文件。
- 写操作前自动备份。
- 导出、备份、日志默认写入用户本地数据目录，不写入程序安装目录。
- 源码仓库通过 `.gitignore` 排除导出、备份、日志和构建产物，避免误提交聊天记录。
- Web 服务只绑定 `127.0.0.1`。

公开发布前请确认不要提交以下内容：

- `exports/`
- `backups/`
- `logs/`
- `docs/界面截图/`
- `.env`
- token、密码、Cookie、私钥或其他敏感信息

## 测试

公开仓库自检，不依赖真实 `.codex`：

```powershell
python .\tests\公开仓库自检.py
```

只读冒烟测试：

```powershell
python .\tests\冒烟测试.py
```

带写操作的归档/恢复回环测试：

```powershell
python .\tests\冒烟测试.py --write
```

写操作测试会自动备份，并在测试内恢复状态。

## 自动化验证与发布

本仓库包含两个 GitHub Actions 工作流：

- `CI`：在 push 和 pull request 时运行 `tests/公开仓库自检.py`。
- `Release Windows EXE`：推送 `v*` tag 时自动构建 Windows EXE，并上传到 GitHub Releases。

发布新版本的典型流程：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

工作流完成后，GitHub Releases 中会出现 `CodexHistoryManager.exe`。

## 设计原则

- **本地优先**：所有核心功能围绕本机 `.codex` 数据工作。
- **安全优先**：写操作先备份，导出和备份不进入 Git。
- **可恢复**：重点解决本地历史记录排序、索引和归档状态问题。
- **可读性**：会话正文应能直接阅读，而不是堆成不可辨认的日志。
- **性能可用**：对大会话和大量历史记录做尾部读取、防抖和分批渲染。

## 许可证

本项目采用 MIT License。详见 [LICENSE](LICENSE)。
