# RelaxSH

一个 Shell 终端里的摸鱼工具，当前阶段先专注做“小说阅读”。

这份仓库现在同时支持两种交付方式：

- 开发者安装：`pip install -e .`
- 用户安装：构建 Linux / macOS / Windows 的独立可执行文件

## 当前能力

- `relaxsh`：进入交互式启动器，先选功能，再选小说相关操作
- 启动页会显示一个终端像素风小图案
- 主页面支持“设置”，可在中文 / English 界面之间切换，且会持久化保存
- `relaxsh import <txt或目录>`：导入单本 TXT 或整个小说目录
- `relaxsh library`：查看书架、进度条、已读百分比和上次阅读时间
- `relaxsh open <书籍ID或标题>`：打开已导入小说
- `relaxsh continue`：继续最近一本已阅读小说
- `relaxsh read <txt文件>`：直接打开单本 TXT，同时自动纳入书架并保存阅读记录
- `relaxsh demo`：直接打开仓库内置示例文本
- `relaxsh version`：查看当前版本

## 当前范围

这版先只收敛在下面 9 项，后续默认不再扩功能：

- [x] 老板键
- [x] 导入单本 / 文件夹
- [x] 每本书阅读记录
- [x] 阅读百分比
- [x] 书架
- [x] 章节识别与跳转
- [x] 搜索
- [x] 书签
- [x] 伪装模式

阅读时支持：

- 单键阅读，不需要按回车
- `d`：下一页
- `a`：上一页
- `s`：下移一行
- `w`：上移一行
- `/`：输入关键词后在书内搜索
- `r`：继续查找上一个关键词的下一个命中
- `g` / `G`：跳到开头 / 结尾
- `m`：打开章节目录
- `[` / `]`：上一章 / 下一章
- `k`：保存当前页为书签/摘录
- `v`：打开书签列表并跳回保存位置
- `b`：老板键，切到伪装工作面板
- `q`：退出

书架数据当前会自动保存：

- 每本书单独阅读记录
- 每本书的已读百分比
- 上次阅读位置
- 最近阅读时间
- 每本书自己的书签和摘录

## 快速开始

### 1. 作为 Python CLI 安装

要求本机有 Python 3.11+。

```bash
python -m pip install -e .
relaxsh
```

启动后当前会先显示：

```text
1. 小说阅读
2. 设置
0. 退出
```

进入“设置”后，可以切换：

- 中文
- English

进入“小说阅读”后，再显示：

```text
1. 导入小说（单个 TXT 或文件夹）
2. 打开书架
3. 继续上次阅读
0. 返回上一级
```

“打开书架”现在会进入一个单独的书架页：

- 直接输入序号就能打开对应小说
- 书架会显示进度条和百分比
- 支持输入 `/关键词` 在书架里筛选小说
- 支持输入 `r` 清空当前筛选
- 可以在书架页里继续最近阅读
- 可以在书架页里继续导入新小说

如果你更喜欢命令式用法，也可以继续直接执行：

```bash
relaxsh import ./novels
relaxsh library
relaxsh open 三体
```

如果你只想体验一下，也可以直接：

```bash
python -m relaxsh demo
```

如果你想不经过导入直接阅读单本：

```bash
relaxsh read ./my-novel.txt
```

### 2. 构建独立二进制

本地构建单平台可执行文件：

```bash
python -m pip install .[release]
python -m PyInstaller packaging/relaxsh.spec
```

构建完成后可以在 `dist/` 目录找到结果：

- macOS / Linux: `dist/relaxsh`
- Windows: `dist/relaxsh.exe`

说明：

- Python 无法在一台机器上原生交叉编译三端二进制
- 仓库已经附带 GitHub Actions 工作流
- 推送 tag 或手动触发后，会分别在 Linux / macOS / Windows 上构建对应产物

## GitHub Actions

仓库内置了 [`.github/workflows/release.yml`](/Users/xgy/Desktop/GY/资料/buer/dream/RelaxSH/.github/workflows/release.yml)：

- 在三种操作系统上跑测试
- 构建独立单文件二进制
- 上传构建产物到 Actions Artifacts

如果你后面要接 GitHub Releases，可以在这个工作流基础上继续补“自动附加 release 资产”。

## 项目结构

```text
.
├── .github/workflows/release.yml
├── packaging/relaxsh.spec
├── pyproject.toml
├── src/relaxsh
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── library.py
│   ├── reader.py
│   └── data/demo.txt
└── tests
    ├── test_cli.py
    └── test_library.py
```

## 设计取舍

- 运行时依赖保持为 0，先用标准库把跨平台基础打稳
- `pip install` 负责开发和本地调试体验
- PyInstaller 负责生成面向最终用户的独立可执行文件
- 阅读器先聚焦 TXT 小说，书架和单书进度优先做扎实
- 老板键采用纯标准库单键输入方案，兼顾 Linux、macOS、Windows
- 阅读位置按字符偏移保存，而不是按页码死存，终端大小变化时更容易恢复

## 状态存储

RelaxSH 默认把书架和阅读记录存到本地 JSON：

- Linux: `~/.local/share/relaxsh/library.json`
- macOS: `~/Library/Application Support/RelaxSH/library.json`
- Windows: `%APPDATA%\\RelaxSH\\library.json`

测试或自定义环境下，也可以通过 `RELAXSH_HOME` 覆盖目录。

## 后续建议

下一步最值得继续做的功能通常是：

1. 章节识别和目录跳转
2. 书签和摘录
3. 伪装主题切换，比如日志流 / 监控面板 / CI 输出
4. 书架搜索和最近阅读排序增强
