# RelaxSH

[English README](./README_EN.md)

一个跨平台的终端 TXT 小说阅读器。

RelaxSH 更适合这样的场景：上班环境里只能开终端，想低调摸鱼偷偷看小说，又不想暴露得太明显。它是一个支持 **Linux / macOS / Windows** 的 **CLI 小说阅读器**、**TXT 阅读器**、**命令行电子书阅读工具**。

## 为什么用它

- 输入 `relaxsh` 就能进入交互式菜单，不需要记复杂命令。
- 支持导入单个 TXT，也支持一次导入整个小说文件夹。
- 每本书都有独立阅读进度、阅读百分比、书签和最近阅读记录。
- 自动识别章节，支持章节目录和章节跳转。
- 支持书内搜索、最近续读、终端书架管理。
- 老板键使用系统原生方案：
  - macOS / Linux：真实 `top`
  - Windows：真实任务管理器
- 阅读状态保存在本地，换一个 shell 或重新打开终端也能接着读。
- 界面支持中文和 English 切换。

## 核心特性

- 交互式启动页
- 终端书架
- 单本 TXT 导入
- 文件夹批量导入
- 每本书独立阅读进度
- 阅读百分比
- 章节识别与章节跳转
- 书内搜索
- 书签
- 原生老板键
- 双语界面

## 安装

### 作为 Python CLI 使用

要求：

- Python 3.8+

安装：

```bash
python -m pip install .
```

本地开发模式安装：

```bash
python -m pip install -e .
```

运行：

```bash
relaxsh
```

### 构建独立二进制

如果你想给不装 Python 的用户使用，可以直接构建独立可执行文件：

```bash
python -m pip install .[release]
python -m PyInstaller packaging/relaxsh.spec
```

输出位置：

- macOS / Linux：`dist/relaxsh`
- Windows：`dist/relaxsh.exe`

## 快速开始

启动 RelaxSH：

```bash
relaxsh
```

当前主界面：

```text
1. 小说阅读
2. 设置
b. 老板键
0. 退出
```

进入“小说阅读”后，可以：

- 导入 TXT 小说
- 打开书架
- 继续上次阅读
- 在菜单里或阅读时触发老板键

## 老板键

在 macOS 和 Linux 上，老板键会打开真实 `top`。按 `q` 退出 `top` 后回到 RelaxSH。

在 Windows 上，老板键会打开真实任务管理器。关闭任务管理器后回到 RelaxSH。

如果系统原生命令不可用，RelaxSH 会退回到内置伪装页。

## 搜索关键词

如果你在找这些方向的工具，RelaxSH 基本都匹配：

`terminal novel reader`, `cli novel reader`, `txt reader`, `command line ebook reader`, `cross-platform reader`, `linux novel reader`, `macos terminal reader`, `windows txt reader`, `boss key`, `bookshelf`, `bookmarks`, `chapter navigation`, `reading progress`, `shell reader`, `python cli`

## 产品简介

RelaxSH 是一个专注于 TXT 小说阅读的终端工具。它把书架、章节跳转、书签、搜索、阅读进度和真实老板键整合到一个轻量 CLI 里，适合想在 shell 里安静读书、又希望体验完整一点的人。
