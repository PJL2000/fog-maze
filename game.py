"""核心游戏逻辑与地图渲染（不依赖具体终端，方便测试）。

- Difficulty：难度预设
- MazeGame：位置、步数、迷雾、提示、计时
- render_view：根据当前可见/已知信息生成画面格子（不含 ANSI 颜色）
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable

from fog import compute_fov
from maze_map import DIRECTIONS, EXIT, START, WALL, MazeMap

Point = tuple[int, int]

DIRECTION_ARROWS = {"up": "↑", "down": "↓", "left": "←", "right": "→"}
DIRECTION_NAMES = {"up": "上", "down": "下", "left": "左", "right": "右"}

FLOOR_VISIBLE = "."
FLOOR_MEMORY = "·"


@dataclass(frozen=True)
class Difficulty:
    key: str
    name: str
    radius: int
    remember: bool
    hints: int | None          # None 表示无限次
    unstable_vision: bool = False
    show_distance: bool = False
    summary: str = ""


DIFFICULTIES: tuple[Difficulty, ...] = (
    Difficulty(
        key="easy",
        name="轻松",
        radius=7,
        remember=True,
        hints=None,
        show_distance=True,
        summary="视野 7 格 · 记住走过的路 · 无限提示 · 显示距出口步数",
    ),
    Difficulty(
        key="normal",
        name="普通",
        radius=5,
        remember=True,
        hints=3,
        summary="视野 5 格 · 记住走过的路 · 3 次提示",
    ),
    Difficulty(
        key="hard",
        name="困难",
        radius=3,
        remember=False,
        hints=0,
        summary="视野 3 格 · 不记路 · 无提示",
    ),
    Difficulty(
        key="nightmare",
        name="噩梦",
        radius=2,
        remember=False,
        hints=0,
        unstable_vision=True,
        summary="视野 1~3 格波动 · 不记路 · 无提示",
    ),
)

DEFAULT_DIFFICULTY = "normal"


def get_difficulty(key: str) -> Difficulty:
    for difficulty in DIFFICULTIES:
        if difficulty.key == key:
            return difficulty
    raise KeyError(f"未知难度: {key}")


@dataclass(frozen=True)
class MoveResult:
    moved: bool
    won: bool = False
    blocked: bool = False


class MazeGame:
    """一局游戏的全部状态。"""

    def __init__(
        self,
        maze: MazeMap,
        difficulty: Difficulty,
        *,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.maze = maze
        self.difficulty = difficulty
        self.rng = rng or random.Random()
        self.clock = clock

        self.position: Point = maze.start
        self.steps = 0
        self.hints_left: int | None = difficulty.hints
        self.started_at = clock()
        self.finished_at: float | None = None
        self.message = "用 WASD 或方向键出发吧"
        self.message_kind = "info"

        # 开局只知道：最外围的墙 + 入口
        self.explored: set[Point] = set(maze.border_walls()) | {maze.start}
        # 无论是否记得路，都记录"曾经看见过"的格子，用于统计探索度
        self.seen_ever: set[Point] = set(self.explored)
        self.visible: frozenset[Point] = frozenset()
        self.exit_seen = False
        self.current_radius = difficulty.radius

        # 出口到各格的最短距离，提示用
        self._dist_to_exit = maze.distances_from(maze.exit)

        self._refresh_vision()

    # ---------- 状态查询 ----------

    @property
    def won(self) -> bool:
        return self.finished_at is not None

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else self.clock()
        return max(0.0, end - self.started_at)

    @property
    def distance_to_exit(self) -> int | None:
        return self._dist_to_exit.get(self.position)

    @property
    def explored_ratio(self) -> float:
        floors = self.maze.floor_cells
        if not floors:
            return 0.0
        seen = self.explored | self.seen_ever
        return len(seen & floors) / len(floors)

    # ---------- 内部 ----------

    def _pick_radius(self) -> int:
        base = self.difficulty.radius
        if not self.difficulty.unstable_vision:
            return base
        # 迷雾像呼吸一样一涨一落：25% 缩小、50% 不变、25% 放大
        return max(1, base + self.rng.choices((-1, 0, 1), weights=(1, 2, 1))[0])

    def _refresh_vision(self) -> None:
        self.current_radius = self._pick_radius()
        seen = compute_fov(self.maze.is_wall, self.position, self.current_radius)
        self.visible = frozenset(p for p in seen if self.maze.is_inside(*p))
        if self.maze.exit in self.visible:
            self.exit_seen = True
        self.seen_ever |= self.visible
        if self.difficulty.remember:
            self.explored |= self.visible

    def _set_message(self, text: str, kind: str = "info") -> None:
        self.message = text
        self.message_kind = kind

    # ---------- 操作 ----------

    def move(self, direction: str) -> MoveResult:
        if self.won:
            return MoveResult(moved=False)
        try:
            dr, dc = DIRECTIONS[direction]
        except KeyError:
            return MoveResult(moved=False)

        target = (self.position[0] + dr, self.position[1] + dc)
        if self.maze.is_wall(*target):
            self._set_message(f"{DIRECTION_NAMES[direction]}边是墙", "warn")
            return MoveResult(moved=False, blocked=True)

        self.position = target
        self.steps += 1
        self._refresh_vision()

        if target == self.maze.exit:
            self.finished_at = self.clock()
            self._set_message("你找到了出口！", "good")
            return MoveResult(moved=True, won=True)

        self._set_message("")
        return MoveResult(moved=True)

    def hint(self) -> str | None:
        """返回提示文字；没有提示次数时返回 None。"""
        if self.won:
            return None
        if self.difficulty.hints == 0:
            self._set_message("这个难度没有提示，靠自己和地图吧", "warn")
            return None
        if self.hints_left == 0:
            self._set_message("提示次数已经用完了", "warn")
            return None

        here = self._dist_to_exit.get(self.position)
        if here is None:
            return None

        best: tuple[int, str] | None = None
        for name, (dr, dc) in DIRECTIONS.items():
            nxt = (self.position[0] + dr, self.position[1] + dc)
            dist = self._dist_to_exit.get(nxt)
            if dist is None:
                continue
            if best is None or dist < best[0]:
                best = (dist, name)
        if best is None:
            return None

        if self.hints_left is not None:
            self.hints_left -= 1

        remaining, direction = best
        text = f"提示：下一步走 {DIRECTION_ARROWS[direction]}（距出口 {here} 步）"
        self._set_message(text, "hint")
        return text


# ---------- 渲染 ----------


@dataclass(frozen=True)
class Cell:
    char: str
    kind: str


@dataclass(frozen=True)
class View:
    rows: tuple[tuple[Cell, ...], ...]
    top: int
    left: int
    full: bool

    def width(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    def height(self) -> int:
        return len(self.rows)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def render_view(game: MazeGame, width: int, height: int) -> View:
    maze = game.maze
    width = max(1, min(width, maze.cols))
    height = max(1, min(height, maze.rows))
    full = maze.cols <= width and maze.rows <= height

    if full:
        top, left = 0, 0
    else:
        top = _clamp(game.position[0] - height // 2, 0, maze.rows - height)
        left = _clamp(game.position[1] - width // 2, 0, maze.cols - width)

    rows: list[tuple[Cell, ...]] = []
    for r in range(top, top + height):
        row: list[Cell] = []
        for c in range(left, left + width):
            point = (r, c)
            if point == game.position:
                row.append(Cell("@", "player"))
                continue

            visible = point in game.visible
            known = point in game.explored
            tile = maze.grid[r][c]

            if visible:
                if tile == WALL:
                    row.append(Cell("#", "wall_lit"))
                elif tile == EXIT:
                    row.append(Cell("E", "exit_lit"))
                elif tile == START:
                    row.append(Cell("S", "entry_lit"))
                else:
                    row.append(Cell(FLOOR_VISIBLE, "floor_lit"))
            elif known:
                if tile == WALL:
                    row.append(Cell("#", "wall_memory"))
                elif tile == EXIT:
                    row.append(Cell("E", "exit_memory"))
                elif tile == START:
                    row.append(Cell("S", "entry"))
                else:
                    row.append(Cell(FLOOR_MEMORY, "floor_memory"))
            else:
                row.append(Cell(" ", "void"))
        rows.append(tuple(row))

    return View(rows=tuple(rows), top=top, left=left, full=full)
