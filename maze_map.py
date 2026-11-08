"""地图解析：读取文本地图、校验合法性、BFS 距离。

地图文件格式
------------
以 `;` 开头的行是注释/元信息（`; name: 名字`、`; desc: 说明`），写在地图之前；
其余每一行都按原样解析：

    #   墙         . 或空格   通道         S   入口（开在最外圈）        E   出口（在地图内部）

要求：有且仅有一个 S 和一个 E；S 必须开在最外圈；E 必须在内部；
除 S 外最外圈全是墙；地图内所有通道互相连通；S 到 E 至少 MIN_DISTANCE 步。

玩家开局只知道"最外围的墙 + 入口"，所以出口不放在外圈上，避免一开局就暴露。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

WALL = "#"
START = "S"
EXIT = "E"

# 可作为通道书写的字符（解析时统一视作可行走地面）
FLOOR_ALIASES = frozenset({" ", ".", "·", "_"})

# 方向名 -> (行增量, 列增量)
DIRECTIONS: dict[str, tuple[int, int]] = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}

Point = tuple[int, int]

MIN_DISTANCE = 12


class MapError(ValueError):
    """地图文件格式或内容非法。"""


@dataclass(frozen=True)
class MazeMap:
    name: str
    grid: tuple[str, ...]           # 每行等长的字符网格
    start: Point                    # (row, col) 入口，位于最外圈
    exit: Point                     # (row, col) 出口，位于内部
    desc: str = ""
    source: Path | None = None

    @property
    def rows(self) -> int:
        return len(self.grid)

    @property
    def cols(self) -> int:
        return len(self.grid[0])

    @property
    def floor_cells(self) -> set[Point]:
        return {
            (r, c)
            for r, row in enumerate(self.grid)
            for c, ch in enumerate(row)
            if ch != WALL
        }

    def is_inside(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols

    def is_wall(self, row: int, col: int) -> bool:
        """界外一律视为墙：既走不出去，也看不穿。"""
        if not self.is_inside(row, col):
            return True
        return self.grid[row][col] == WALL

    def is_border(self, row: int, col: int) -> bool:
        return row in (0, self.rows - 1) or col in (0, self.cols - 1)

    def border_walls(self) -> set[Point]:
        """开局就已知的外围墙。"""
        return {
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if self.is_border(r, c) and self.grid[r][c] == WALL
        }

    def neighbors(self, row: int, col: int) -> Iterable[Point]:
        for dr, dc in DIRECTIONS.values():
            yield row + dr, col + dc

    def open_neighbors(self, row: int, col: int) -> list[Point]:
        return [(r, c) for r, c in self.neighbors(row, col) if not self.is_wall(r, c)]

    def distances_from(self, origin: Point) -> dict[Point, int]:
        """BFS：origin 到各可行走格子的最短步数。"""
        dist = {origin: 0}
        queue = deque([origin])
        while queue:
            r, c = queue.popleft()
            for nxt in self.open_neighbors(r, c):
                if nxt not in dist:
                    dist[nxt] = dist[(r, c)] + 1
                    queue.append(nxt)
        return dist


def _parse_header(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """剥离顶部 `; 键: 值` 元信息，返回 (元信息, 地图本体行)。"""
    meta: dict[str, str] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(";"):
            key, sep, value = stripped.lstrip(";").partition(":")
            if sep and key.strip():
                meta[key.strip().lower()] = value.strip()
            continue
        return meta, lines[index:]
    return meta, []


def load_map(path: str | Path) -> MazeMap:
    """从文本文件加载并校验地图。"""
    path = Path(path)
    if not path.is_file():
        raise MapError(f"找不到地图文件: {path}")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MapError(f"地图不是 UTF-8 文本: {path.name}") from exc

    meta, body = _parse_header(raw.splitlines())
    body = [line.rstrip("\r") for line in body]
    while body and not body[-1].strip():
        body.pop()
    if not body:
        raise MapError(f"地图为空: {path.name}")

    width = max(len(line) for line in body)
    grid = tuple(line.ljust(width) for line in body)

    allowed = {WALL, START, EXIT} | FLOOR_ALIASES
    starts: list[Point] = []
    exits: list[Point] = []
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch not in allowed:
                raise MapError(
                    f"{path.name}: 第 {r + 1} 行第 {c + 1} 列出现非法字符 {ch!r}"
                )
            if ch == START:
                starts.append((r, c))
            elif ch == EXIT:
                exits.append((r, c))

    if len(starts) != 1:
        raise MapError(f"{path.name}: 需要恰好 1 个入口 S，当前 {len(starts)} 个")
    if len(exits) != 1:
        raise MapError(f"{path.name}: 需要恰好 1 个出口 E，当前 {len(exits)} 个")

    maze = MazeMap(
        name=meta.get("name") or path.stem,
        grid=grid,
        start=starts[0],
        exit=exits[0],
        desc=meta.get("desc", ""),
        source=path,
    )
    _validate(maze)
    return maze


def _validate(maze: MazeMap) -> None:
    if maze.rows < 8 or maze.cols < 8:
        raise MapError(f"{maze.name}: 地图太小（至少 8x8）")

    for r in range(maze.rows):
        for c in range(maze.cols):
            if not maze.is_border(r, c):
                continue
            if maze.grid[r][c] not in (WALL, START):
                raise MapError(
                    f"{maze.name}: 最外圈第 {r + 1} 行第 {c + 1} 列必须是墙"
                    f"（只允许入口 S 开在外圈）"
                )

    if not maze.is_border(*maze.start):
        raise MapError(f"{maze.name}: 入口 S 必须开在最外圈上")
    if maze.is_border(*maze.exit):
        raise MapError(f"{maze.name}: 出口 E 必须放在地图内部（否则开局就暴露了）")

    if not maze.open_neighbors(*maze.start):
        raise MapError(f"{maze.name}: 入口没有连到迷宫内部")
    if not maze.open_neighbors(*maze.exit):
        raise MapError(f"{maze.name}: 出口被墙完全封死")

    reachable = maze.distances_from(maze.start)
    if maze.exit not in reachable:
        raise MapError(f"{maze.name}: 入口无法走到出口")
    if reachable[maze.exit] < MIN_DISTANCE:
        raise MapError(
            f"{maze.name}: 入口到出口只有 {reachable[maze.exit]} 步，太近了"
            f"（至少要 {MIN_DISTANCE} 步）"
        )
    unreachable = maze.floor_cells - reachable.keys()
    if unreachable:
        r, c = min(unreachable)
        raise MapError(
            f"{maze.name}: 存在走不到的通道，例如第 {r + 1} 行第 {c + 1} 列"
        )


def discover_maps(folder: str | Path) -> list[tuple[Path, MazeMap | str]]:
    """扫描目录下全部 .txt，返回 (路径, 地图或错误文字)。"""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found: list[tuple[Path, MazeMap | str]] = []
    for path in sorted(folder.glob("*.txt")):
        try:
            found.append((path, load_map(path)))
        except MapError as exc:
            found.append((path, str(exc)))
    return found
