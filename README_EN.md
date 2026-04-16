# RelaxSH

[中文说明](./README.md)

Cross-platform terminal novel reader for TXT fiction.

RelaxSH is built for people who want a clean **terminal novel reader**, **CLI TXT reader**, **command-line ebook reader**, and **cross-platform reading app** on **Linux**, **macOS**, and **Windows**.

## Why RelaxSH

- Launch with `relaxsh` and enter an interactive menu instead of memorizing long commands.
- Import one TXT file or a whole folder of novels.
- Keep per-book reading progress, reading percentage, bookmarks, and recent activity.
- Detect chapters automatically for chapter jump and chapter browsing.
- Search inside the book, continue from the latest session, and manage a bookshelf in the terminal.
- Use a real boss key:
  - macOS / Linux: open real `top`
  - Windows: open real Task Manager
- Save state locally and keep reading progress across terminal sessions.
- Switch UI language between Chinese and English.

## Key Features

- Interactive launcher
- Terminal bookshelf
- Single TXT import
- Folder import
- Per-book progress tracking
- Reading percentage
- Chapter detection and chapter jump
- In-book search
- Bookmarks
- Native boss key
- Bilingual UI

## Install

### Python CLI

Requirements:

- Python 3.8+

Install:

```bash
python -m pip install .
```

For local development:

```bash
python -m pip install -e .
```

Run:

```bash
relaxsh
```

### Standalone Binary

If you want standalone executables instead of requiring Python:

```bash
python -m pip install .[release]
python -m PyInstaller packaging/relaxsh.spec
```

Output:

- macOS / Linux: `dist/relaxsh`
- Windows: `dist/relaxsh.exe`

## Quick Start

Start RelaxSH:

```bash
relaxsh
```

Current main menu:

```text
1. Novel Reader
2. Settings
b. Boss Key
0. Exit
```

Inside the novel reader, you can:

- import TXT novels
- open your bookshelf
- continue the last book
- trigger the boss key from menus or during reading

## Boss Key

On macOS and Linux, the boss key opens real `top`. Press `q` to leave `top` and return to RelaxSH.

On Windows, the boss key opens real Task Manager. Close Task Manager to return to RelaxSH.

If the native system command is unavailable, RelaxSH falls back to its built-in disguise screen.

## Search Keywords

RelaxSH is relevant if you are searching for:

`terminal novel reader`, `cli novel reader`, `txt reader`, `command line ebook reader`, `cross-platform reader`, `linux novel reader`, `macos terminal reader`, `windows txt reader`, `boss key`, `bookshelf`, `bookmarks`, `chapter navigation`, `reading progress`, `shell reader`, `python cli`

## Product Summary

RelaxSH is a terminal-based novel reader focused on TXT files. It combines a CLI bookshelf, chapter navigation, bookmark support, search, progress tracking, and a real boss key into one lightweight tool. It is designed for users who want a distraction-free reading experience in the shell without giving up usability.
