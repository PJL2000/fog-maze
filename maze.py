"""迷雾迷宫 —— 命令行二维走迷宫。

直接运行即可进入菜单：

    python maze.py

常用参数：
    python maze.py -d hard                 指定默认难度
    python maze.py -m maps/01_intro.txt    直接开始某张地图
    python maze.py --maps                列出所有地图
    python maze.py --check               校验 maps 目录下所有地图
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from game import DIFFICULTIES, DEFAULT_DIFFICULTY, get_difficulty
from maze_map import MapError, MazeMap, discover_maps, load_map

def _app_dir() -> Path:
    """程序自身所在目录。打包后指向 exe 旁边，而不是临时解压目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_dir() -> Path:
    """只读资源目录。打包后是 PyInstaller 的临时解压目录，源码运行时同 _app_dir()。"""
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else _app_dir()


def _default_maps_dir() -> Path:
    """默认地图目录：exe/仓库旁的 maps 优先，没有就用打进包里的那份。"""
    external = _app_dir() / "maps"
    if external.is_dir():
        return external
    return _bundle_dir() / "maps"


BASE_DIR = _app_dir()
MAPS_DIR = _default_maps_dir()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="maze.py",
        description="迷雾迷宫：命令行二维走迷宫，带真实视野迷雾。",
    )
    parser.add_argument(
        "-m",
        "--map",
        metavar="文件",
        help="直接开始指定地图（.txt），跳过菜单",
    )
    parser.add_argument(
        "-d",
        "--difficulty",
        metavar="难度",
        default=DEFAULT_DIFFICULTY,
        help="默认难度：" + " / ".join(d.key for d in DIFFICULTIES),
    )
    parser.add_argument("--maps", action="store_true", help="列出内置地图后退出")
    parser.add_argument("--check", action="store_true", help="校验地图文件后退出")
    parser.add_argument("--no-color", action="store_true", help="关闭颜色")
    parser.add_argument(
        "--maps-dir",
        metavar="目录",
        default=str(MAPS_DIR),
        help="地图目录（默认 maps/）",
    )
    return parser.parse_args(argv)


def _make_console_safe() -> None:
    """避免控制台编码（如 GBK）不支持某些字符时直接崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _make_console_safe()
    args = parse_args(argv)
    maps_dir = Path(args.maps_dir)
    if not maps_dir.is_absolute():
        maps_dir = (BASE_DIR / maps_dir).resolve()

    try:
        get_difficulty(args.difficulty)
    except KeyError:
        print(f"未知难度：{args.difficulty}")
        print("可选：" + " / ".join(d.key for d in DIFFICULTIES))
        return 2

    entries = discover_maps(maps_dir)

    if args.check:
        return _check_maps(entries, maps_dir)
    if args.maps:
        return _list_maps(entries, maps_dir)

    direct_map: Path | None = None
    if args.map:
        direct_map = Path(args.map).expanduser()
        if not direct_map.is_absolute():
            direct_map = (Path.cwd() / direct_map).resolve()
        try:
            load_map(direct_map)
        except MapError as exc:
            print(f"地图无法载入：{exc}")
            return 2

    try:
        from ui import run
    except ImportError as exc:  # pragma: no cover - 正常安装不会触发
        print(f"界面模块不可用：{exc}")
        return 1

    try:
        return run(
            entries=entries,
            default_difficulty=args.difficulty,
            color=not args.no_color,
            direct_map=direct_map,
            direct_difficulty=None,
        )
    except KeyboardInterrupt:
        print("\n已退出。")
        return 130


def _describe(entry: tuple[Path, MazeMap | str]) -> str:
    path, maze = entry
    if isinstance(maze, str):
        return f"  [X] {path.name:<22} {maze}"
    return f"  [OK] {path.name:<22} {maze.name}  {maze.rows}x{maze.cols}  {maze.desc}"


def _list_maps(entries: list[tuple[Path, MazeMap | str]], maps_dir: Path) -> int:
    if not entries:
        print(f"地图目录为空或不存在：{maps_dir}")
        return 1
    print(f"地图目录：{maps_dir}")
    print(f"共 {len(entries)} 个文件")
    for entry in entries:
        print(_describe(entry))
    return 0


def _check_maps(entries: list[tuple[Path, MazeMap | str]], maps_dir: Path) -> int:
    if not entries:
        print(f"地图目录为空或不存在：{maps_dir}")
        return 1
    bad = 0
    for entry in entries:
        print(_describe(entry))
        if isinstance(entry[1], str):
            bad += 1
    print(f"\n通过 {len(entries) - bad} / {len(entries)}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
