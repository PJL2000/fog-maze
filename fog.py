"""真实迷雾：逐格视线检测。

玩家能看到的，只有"从当前位置出发、直线没有被墙挡住"的格子；
墙本身会被照亮（所以你能看到挡路的墙），但墙背后的空间不会泄露。

算法用 Amanatides-Woo 体素遍历沿直线逐格推进，遇到墙即判定被遮挡。
由于视野半径很小（最多 9 格），每次移动重算一遍的开销可以忽略。
"""

from __future__ import annotations

from collections.abc import Callable
from math import inf

Point = tuple[int, int]

_EPS = 1e-12


def line_of_sight(
    is_wall: Callable[[int, int], bool],
    start: Point,
    end: Point,
) -> bool:
    """start 与 end 之间是否通透（对称的）。

    只检查中间格子：终点自身是不是墙不影响判定——正因如此，被照亮的墙
    才会出现在视野里，而它背后的格子被它挡住。
    斜向穿过两个墙角的缝隙不算通透（避免从墙角"偷看"）。
    """
    if start == end:
        return True

    (r0, c0), (r1, c1) = start, end
    dr, dc = r1 - r0, c1 - c0
    adr, adc = abs(dr), abs(dc)
    step_r = (dr > 0) - (dr < 0)
    step_c = (dc > 0) - (dc < 0)

    t_delta_r = 1.0 / adr if adr else inf
    t_delta_c = 1.0 / adc if adc else inf
    t_max_r = 0.5 * t_delta_r if adr else inf
    t_max_c = 0.5 * t_delta_c if adc else inf

    r, c = r0, c0
    for _ in range(adr + adc + 2):
        if (r, c) == (r1, c1):
            break
        if abs(t_max_r - t_max_c) < _EPS:
            # 正好穿过格点：对角移动，两个正交邻格都堵死时不能穿
            if is_wall(r + step_r, c) and is_wall(r, c + step_c):
                return False
            r += step_r
            c += step_c
            t_max_r += t_delta_r
            t_max_c += t_delta_c
        elif t_max_r < t_max_c:
            r += step_r
            t_max_r += t_delta_r
        else:
            c += step_c
            t_max_c += t_delta_c

        if (r, c) != (r1, c1) and is_wall(r, c):
            return False
    return (r, c) == (r1, c1)


def compute_fov(
    is_wall: Callable[[int, int], bool],
    origin: Point,
    radius: int,
) -> set[Point]:
    """返回 origin 周围圆形范围内可见的格子集合（含 origin 本身）。

    radius = 1 时只看得见上下左右四格；半径越大看得越远。
    界外坐标交给 is_wall 判断（MazeMap.is_wall 把界外当墙），
    调用方通常需要再按地图尺寸过滤一遍。
    """
    if radius < 1:
        return {origin}

    ox, oy = origin
    visible: set[Point] = {origin}
    radius_sq = radius * radius
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr == 0 and dc == 0:
                continue
            if dr * dr + dc * dc > radius_sq:
                continue
            target = (ox + dr, oy + dc)
            if line_of_sight(is_wall, origin, target):
                visible.add(target)
    return visible
