"""终端交互层：按键读取、配色、整屏绘制、菜单。

界面刻意保持朴素：只用字符画，不依赖第三方库。
"""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from game import (
    DIFFICULTIES,
    Difficulty,
    MazeGame,
    get_difficulty,
    render_view,
)
from maze_map import MazeMap, load_map

KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT = "up", "down", "left", "right"
KEY_ENTER, KEY_OTHER, KEY_EOF = "enter", "other", "eof"

MOVE_KEYS = frozenset({KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT})

_COLORS = {
    "wall_lit": "\x1b[1;97m",
    "wall_memory": "\x1b[90m",
    "floor_lit": "\x1b[37m",
    "floor_memory": "\x1b[90m",
    "player": "\x1b[1;33m",
    "exit_lit": "\x1b[1;32m",
    "exit_memory": "\x1b[32m",
    "entry_lit": "\x1b[36m",
    "entry": "\x1b[36m",
    "info": "\x1b[36m",
    "good": "\x1b[1;32m",
    "warn": "\x1b[1;33m",
    "hint": "\x1b[1;35m",
}
_RESET = "\x1b[0m"

_KEY_CHARS = {
    "w": KEY_UP,
    "s": KEY_DOWN,
    "a": KEY_LEFT,
    "d": KEY_RIGHT,
    "W": KEY_UP,
    "S": KEY_DOWN,
    "A": KEY_LEFT,
    "D": KEY_RIGHT,
}


# --------------------------------------------------------------------------
# 终端能力
# --------------------------------------------------------------------------


def enable_ansi() -> bool:
    """让 Windows 控制台支持 ANSI 转义；其它平台默认支持。"""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def display_width(text: str) -> int:
    """按终端列宽估算字符串宽度（中文按 2 列算）。"""
    return sum(
        0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        for ch in text
    )


def truncate_display(text: str, width: int) -> str:
    """按显示宽度截断，超出部分用 … 结尾。"""
    if display_width(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if used + w > width - 1:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def center_display(text: str, width: int) -> str:
    gap = max(0, width - display_width(text))
    left = gap // 2
    return " " * left + text + " " * (gap - left)


@dataclass(frozen=True)
class Terminal:
    width: int
    height: int
    ansi: bool


def detect_terminal(color: bool = True) -> Terminal:
    size = shutil.get_terminal_size(fallback=(80, 24))
    ansi = bool(color and sys.stdout.isatty() and enable_ansi())
    return Terminal(max(24, size.columns), max(10, size.lines), ansi)


# --------------------------------------------------------------------------
# 按键
# --------------------------------------------------------------------------


def normalize_key(ch: str) -> str:
    if ch in _KEY_CHARS:
        return _KEY_CHARS[ch]
    if ch in ("\r", "\n"):
        return KEY_ENTER
    if ch == "\x03":  # Ctrl+C
        return KEY_EOF
    return ch.lower()


class KeyReader(AbstractContextManager):
    """逐键读取。Windows 用 msvcrt，POSIX 用 termios 的 cbreak 模式。

    标准输入不是终端时（管道输入），退化为逐行读取、取每行首个字符。
    """

    def __init__(self) -> None:
        self._tty = sys.stdin.isatty()
        self._fd: int | None = None
        self._saved = None
        self._windows = os.name == "nt"

    def __enter__(self) -> KeyReader:
        if self._tty and not self._windows:
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc_info) -> None:
        if self._fd is not None and self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            self._fd = None

    def read_key(self) -> str:
        if not self._tty:
            line = sys.stdin.readline()
            if not line:
                return KEY_EOF
            text = line.strip()
            return normalize_key(text[0]) if text else KEY_ENTER
        return self._read_windows() if self._windows else self._read_posix()

    def _read_windows(self) -> str:
        import msvcrt

        try:
            ch = msvcrt.getwch()
        except KeyboardInterrupt:
            return KEY_EOF
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": KEY_UP, "P": KEY_DOWN, "K": KEY_LEFT, "M": KEY_RIGHT}.get(
                code, KEY_OTHER
            )
        return normalize_key(ch)

    def _read_posix(self) -> str:
        import select

        assert self._fd is not None
        first = os.read(self._fd, 1)
        if not first:
            return KEY_EOF
        if first == b"\x1b":
            tail = b""
            for _ in range(2):
                ready, _, _ = select.select([self._fd], [], [], 0.05)
                if not ready:
                    break
                tail += os.read(self._fd, 1)
            arrows = {
                b"[A": KEY_UP,
                b"[B": KEY_DOWN,
                b"[C": KEY_RIGHT,
                b"[D": KEY_LEFT,
                b"OA": KEY_UP,
                b"OB": KEY_DOWN,
                b"OC": KEY_RIGHT,
                b"OD": KEY_LEFT,
            }
            return arrows.get(tail, KEY_EOF)
        return normalize_key(first.decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# 绘制
# --------------------------------------------------------------------------


def colorize(text: str, kind: str, enabled: bool) -> str:
    if not enabled:
        return text
    code = _COLORS.get(kind)
    return f"{code}{text}{_RESET}" if code else text


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _hints_label(game: MazeGame) -> str:
    return "∞" if game.hints_left is None else str(game.hints_left)


def build_frame(game: MazeGame, terminal: Terminal) -> list[str]:
    """把一帧画面拼成若干行字符串（含 ANSI 颜色）。"""
    width = terminal.width
    reserved = 4  # 标题、状态、消息、按键提示
    view = render_view(
        game,
        width=max(10, width - 2),
        height=max(3, min(game.maze.rows, terminal.height - reserved)),
    )

    status = [
        f"步数 {game.steps}",
        f"用时 {format_duration(game.elapsed)}",
        f"提示 {_hints_label(game)}",
        f"探索 {game.explored_ratio:.0%}",
    ]
    if game.difficulty.show_distance and game.distance_to_exit is not None:
        status.append(f"距出口 {game.distance_to_exit} 步")
    if game.difficulty.unstable_vision:
        status.append(f"视野 {game.current_radius}")

    lines = [
        truncate_display(f" {game.maze.name} · {game.difficulty.name}", width),
        truncate_display(" " + "   ".join(status), width),
    ]

    indent = " " * max(0, (width - view.width()) // 2)
    for row in view.rows:
        lines.append(indent + "".join(colorize(cell.char, cell.kind, terminal.ansi) for cell in row))

    if game.won:
        text = " 找到出口！  R 再来一局   其它键返回菜单"
    else:
        text = " " + (game.message or " ")
    lines.append(colorize(truncate_display(text, width), "good" if game.won else game.message_kind, terminal.ansi))
    lines.append(
        colorize(
            truncate_display(" WASD/方向键 移动   H 提示   ? 帮助   R 重开   Q 返回菜单", width),
            "info",
            terminal.ansi,
        )
    )

    while len(lines) < terminal.height:
        lines.append("")
    return lines[: terminal.height]


class Screen(AbstractContextManager):
    """ANSI 时用备用屏幕整屏刷新；否则退化为滚动输出。"""

    def __init__(self, terminal: Terminal) -> None:
        self.terminal = terminal
        self._fullscreen = False

    def __enter__(self) -> Screen:
        if self.terminal.ansi:
            sys.stdout.write("\x1b[?1049h\x1b[?25l")
            sys.stdout.flush()
            self._fullscreen = True
        return self

    def __exit__(self, *exc_info) -> None:
        if self._fullscreen:
            sys.stdout.write(_RESET + "\x1b[?25h\x1b[?1049l")
            sys.stdout.flush()

    def draw(self, lines: list[str]) -> None:
        if self._fullscreen:
            # 先清屏再写，避免上一帧更长时留下残影
            sys.stdout.write(_RESET + "\x1b[H\x1b[J" + "\n".join(lines))
        else:
            sys.stdout.write("\n" + "\n".join(lines) + "\n")
        sys.stdout.flush()


# --------------------------------------------------------------------------
# 菜单
# --------------------------------------------------------------------------


_stdin_closed = False
_interrupted = False


def prompt(text: str) -> str:
    """读一行输入。EOF 或 Ctrl+C 时记下标记，菜单会据此安全退出。"""
    global _stdin_closed, _interrupted
    try:
        return input(text).strip()
    except EOFError:
        _stdin_closed = True
        return ""
    except KeyboardInterrupt:
        _interrupted = True
        return ""


def print_banner(subtitle: str = "") -> None:
    width = min(68, shutil.get_terminal_size(fallback=(80, 24)).columns)
    print("=" * width)
    print(center_display("迷 雾 迷 宫   Fog Maze", width))
    if subtitle:
        print(center_display(subtitle, width))
    print("=" * width)


def _map_line(maze: MazeMap) -> str:
    desc = f"  {maze.desc}" if maze.desc else ""
    return f"{maze.name}  ({maze.rows}x{maze.cols}){desc}"


def choose_map(entries: list[tuple[Path, MazeMap | str]]) -> tuple[Path, MazeMap] | None:
    playable = [(path, maze) for path, maze in entries if isinstance(maze, MazeMap)]
    broken = [(path, err) for path, err in entries if not isinstance(err, MazeMap)]

    print()
    print_banner("选择地图")
    if not playable:
        print("  列表里没有可用的地图。")
        print("  把 .txt 地图放进 maps 文件夹，或用主菜单的「导入地图」。")
        return None
    for index, (_, maze) in enumerate(playable, 1):
        print(f"  {index}) {_map_line(maze)}")
    if broken:
        print(f"  ! 另有 {len(broken)} 个文件无法载入：")
        for path, err in broken[:3]:
            print(f"    - {path.name}：{err}")
        if len(broken) > 3:
            print(f"    … 还有 {len(broken) - 3} 个")
    while True:
        raw = prompt("  输入编号开始（回车返回）：")
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(playable):
            return playable[int(raw) - 1]
        print("  请输入有效编号。")


def choose_difficulty(default_key: str = "normal") -> Difficulty:
    default = get_difficulty(default_key)
    print()
    print_banner("选择难度")
    for index, difficulty in enumerate(DIFFICULTIES, 1):
        mark = "*" if difficulty is default else " "
        print(f" {mark}{index}) {difficulty.name:<4} {difficulty.summary}")
    while True:
        raw = prompt(f"  输入编号（回车 = {default.name}）：")
        if not raw or _aborted():
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(DIFFICULTIES):
            return DIFFICULTIES[int(raw) - 1]
        print("  请输入有效编号。")


HELP_TEXT = """  移动
  W / ↑ 上    A / ← 左    S / ↓ 下    D / → 右
  H 提示    ? 帮助    R 重开    Q 返回主菜单

  迷雾
  · 只能看到当前位置视线能到的地方，墙会挡住视线；
  · 开局只知道最外围的墙和入口，出口要自己摸索；
  · 记住走过的路、提示次数，由难度决定；
  · 「噩梦」难度的视野会忽大忽小。

  地图文件（纯文本 .txt，放在 maps 文件夹）
  ; name: 地图名称
  ; desc: 一句话介绍
  ###########
  #S........#
  #.#######.#
  #.......#E#
  ###########

  # 墙   . 或空格 通道   S 入口   E 出口
  要求：有且只有一个 S 和 E；S 开在最外圈；E 在地图内部；
        除 S 外最外圈必须全是墙；所有通道连通；S 到 E 至少 12 步。
"""


def show_help() -> None:
    print()
    print_banner("玩法与地图格式")
    print(HELP_TEXT)
    prompt("  回车返回。")


def import_map(entries: list[tuple[Path, MazeMap | str]]) -> list[tuple[Path, MazeMap | str]]:
    print()
    print_banner("导入地图")
    print("  输入一个 .txt 地图文件，或包含多张地图的文件夹路径。")
    print("  Windows 下也可以直接把文件拖进窗口（两侧引号会自动去掉）。")
    raw = prompt("  路径：")
    if not raw:
        return entries
    target = Path(raw.strip().strip('"').strip("'")).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if target.is_dir():
        from maze_map import discover_maps

        found = discover_maps(target)
        if not found:
            print(f"  目录中没有 .txt 地图：{target}")
        else:
            known = {path.resolve() for path, _ in entries}
            added = 0
            for path, maze in found:
                if path.resolve() not in known:
                    entries.append((path, maze))
                    known.add(path.resolve())
                    added += 1
            print(f"  目录共 {len(found)} 个文件，新增 {added} 个。")
            for path, maze in found:
                if isinstance(maze, str):
                    print(f"    ! {path.name}：{maze}")
    elif target.is_file():
        try:
            maze = load_map(target)
        except Exception as exc:  # noqa: BLE001 - 直接把原因显示给玩家
            print(f"  载入失败：{exc}")
        else:
            known = {path.resolve() for path, _ in entries}
            if target.resolve() in known:
                print(f"  这张地图已经在列表里：{maze.name}")
            else:
                entries.append((target, maze))
                print(f"  已导入：{maze.name}  ({maze.rows}x{maze.cols})")
    else:
        print(f"  路径不存在：{target}")

    prompt("  回车返回。")
    return entries


# --------------------------------------------------------------------------
# 游戏循环
# --------------------------------------------------------------------------


def _aborted() -> bool:
    return _stdin_closed or _interrupted


def _help_screen(terminal: Terminal, screen: Screen, keys: KeyReader) -> None:
    """在当前游戏画面里显示帮助（不新开备用屏幕，避免退出后画面错乱）。"""
    lines = ["", center_display("玩法速查", terminal.width), ""]
    lines += [truncate_display(line, terminal.width) for line in HELP_TEXT.splitlines()]
    lines += ["", center_display("按任意键继续", terminal.width)]
    while len(lines) < terminal.height:
        lines.append("")
    screen.draw(lines[: terminal.height])
    keys.read_key()


def play(maze: MazeMap, difficulty: Difficulty, terminal: Terminal) -> None:
    game = MazeGame(maze, difficulty)
    with Screen(terminal) as screen, KeyReader() as keys:
        while True:
            screen.draw(build_frame(game, terminal))
            key = keys.read_key()

            if key == KEY_EOF:
                return
            if game.won:
                if key == "r":
                    game = MazeGame(maze, difficulty)
                else:
                    return
                continue

            if key in MOVE_KEYS:
                game.move(key)
            elif key == "h":
                game.hint()
            elif key == "r":
                game = MazeGame(maze, difficulty)
            elif key in ("?", "/"):
                _help_screen(terminal, screen, keys)
            elif key in ("q", "\x1b"):
                return


def run(
    *,
    entries: list[tuple[Path, MazeMap | str]],
    default_difficulty: str = "normal",
    color: bool = True,
    direct_map: Path | None = None,
    direct_difficulty: str | None = None,
) -> int:
    terminal = detect_terminal(color)

    if direct_map is not None:
        play(load_map(direct_map), get_difficulty(direct_difficulty or default_difficulty), terminal)
        return 0

    while True:
        print()
        print_banner("用字符走迷宫，用眼睛探路")
        print("  1) 开始游戏")
        print("  2) 导入地图")
        print("  3) 玩法说明")
        print("  0) 退出")
        raw = prompt("  请选择：")

        if _aborted() or raw in ("0", "q", "Q"):
            print("  下次见。")
            return 0
        if raw in ("3", "?", "/"):
            show_help()
            continue
        if raw == "2":
            entries = import_map(entries)
            continue
        if raw in ("", "1"):
            picked = choose_map(entries)
            if picked is None:
                continue
            difficulty = choose_difficulty(default_difficulty)
            if _aborted():
                print("  下次见。")
                return 0
            play(picked[1], difficulty, terminal)
            continue
        print("  请输入 0 ~ 3。")
