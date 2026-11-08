"""轻量自测：不依赖 pytest，直接 `python tests_smoke.py` 运行。"""

from __future__ import annotations

import random
import sys
from collections import deque
from pathlib import Path

from fog import compute_fov, line_of_sight
from game import DIFFICULTIES, MazeGame, get_difficulty, render_view
from maze_map import discover_maps, load_map
from ui import Terminal, build_frame, display_width

BASE = Path(__file__).resolve().parent
MAPS = BASE / "maps"
DIRS = {(1, 0): "down", (-1, 0): "up", (0, 1): "right", (0, -1): "left"}


def shortest_path(maze, start, goal):
    prev = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        for nxt in maze.open_neighbors(*current):
            if nxt not in prev:
                prev[nxt] = current
                queue.append(nxt)
    path, current = [], goal
    while current is not None and current != start:
        path.append(current)
        current = prev[current]
    return path[::-1]


def check_maps():
    entries = discover_maps(MAPS)
    assert entries, "maps 目录为空"
    for path, maze in entries:
        assert not isinstance(maze, str), f"{path.name}: {maze}"
        dist = maze.distances_from(maze.start)
        assert maze.exit in dist
        assert dist[maze.exit] >= 8
        assert maze.is_wall(-1, 0) and maze.is_wall(maze.rows, 0)
    print(f"地图校验通过：{len(entries)} 张")


def check_fog():
    maze = load_map(MAPS / "04_pillars.txt")
    for radius in (1, 3, 5, 7):
        seen = compute_fov(maze.is_wall, maze.start, radius)
        assert maze.start in seen
        for point in seen:
            assert line_of_sight(maze.is_wall, maze.start, point)
    # 视野范围不能超过半径
    seen = compute_fov(maze.is_wall, (5, 5), 3)
    for r, c in seen:
        assert (r - 5) ** 2 + (c - 5) ** 2 <= 9
    print("迷雾/视线自检通过")


def check_paths():
    for path, maze in discover_maps(MAPS):
        if isinstance(maze, str):
            continue
        route = shortest_path(maze, maze.start, maze.exit)
        for difficulty in DIFFICULTIES:
            game = MazeGame(maze, difficulty, rng=random.Random(1), clock=lambda: 0.0)
            for step in route:
                delta = (step[0] - game.position[0], step[1] - game.position[1])
                assert game.move(DIRS[delta]).moved
            assert game.won, (path.name, difficulty.key)
            assert game.exit_seen
            for size in ((24, 10), (80, 24), (200, 60)):
                frame = build_frame(game, Terminal(*size, False))
                assert len(frame) <= size[1]
                assert all(display_width(line) <= size[0] for line in frame)
    print("通关与渲染自检通过")


def check_difficulty_traits():
    maze = load_map(MAPS / "01_intro.txt")
    hard = MazeGame(maze, get_difficulty("hard"), rng=random.Random(0), clock=lambda: 0.0)
    assert hard.hint() is None and hard.hints_left == 0
    remembered = len(hard.explored)
    hard.move("up")
    hard.move("down")
    assert len(hard.explored) == remembered, "困难难度不应该记路"

    easy = MazeGame(maze, get_difficulty("easy"), rng=random.Random(0), clock=lambda: 0.0)
    before = len(easy.explored)
    easy.move("up")
    if easy.position != maze.start:
        assert len(easy.explored) >= before

    nightmare = MazeGame(maze, get_difficulty("nightmare"), rng=random.Random(0), clock=lambda: 0.0)
    radii = set()
    for _ in range(60):
        nightmare._refresh_vision()
        radii.add(nightmare.current_radius)
    assert radii <= {1, 2, 3} and len(radii) > 1
    print("难度特性自检通过")


def check_viewport():
    maze = load_map(MAPS / "06_labyrinth.txt")
    game = MazeGame(maze, get_difficulty("easy"), rng=random.Random(0), clock=lambda: 0.0)
    view = render_view(game, 40, 12)
    assert view.width() == 40 and view.height() == 12
    assert view.top <= game.position[0] < view.top + 12
    small = render_view(game, 500, 500)
    assert small.full and small.width() == maze.cols
    print("视口裁剪自检通过")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    check_maps()
    check_fog()
    check_paths()
    check_difficulty_traits()
    check_viewport()
    print("全部自检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
