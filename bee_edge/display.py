"""HDMI 显示屏渲染（pygame，纯本地、离线可用）。

设计取向：暗色「蜂场仪表盘」——
  · 深炭绿底 + 淡蜂窝纹理 + 蜂蜜金强调
  · 核心指标「失王概率」用 270° 环形仪表盘呈现
  · 右侧温湿度卡片、顶栏身份/时钟、底栏更新时间/同步状态

读取 state.json；运行在控制台（无 X）时使用 SDL 的 kmsdrm 驱动。
所有绘制先在 1280x800 的设计画布上完成，再按实际分辨率缩放。
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

try:
    import pygame  # type: ignore
except ModuleNotFoundError:  # 允许在无 pygame 的环境导入本模块（如离线测试）
    pygame = None  # type: ignore

from .config import EdgeConfig
from .netinfo import hostname, ipv4_addresses
from .state import read_state

log = logging.getLogger("bee_edge.display")

REFRESH_S = 5.0
DW, DH = 1280, 800  # 设计画布尺寸
CLOCK_RECT = (760, 28, 474, 112)  # 顶栏右上的时钟区（每秒局刷）

# ── 调色板 ────────────────────────────────────────────────
BG = (10, 16, 14)
PANEL = (19, 29, 24)
PANEL_HI = (30, 43, 36)
LINE = (46, 61, 52)
TEXT = (237, 243, 237)
DIM = (128, 143, 133)
FAINT = (84, 97, 89)
HONEY = (246, 183, 62)
TEAL = (88, 198, 184)
TONE = {
    "ok": (54, 196, 130),
    "warn": (246, 178, 58),
    "danger": (233, 86, 72),
    "neutral": (150, 162, 152),
}

# ── 字体 ──────────────────────────────────────────────────
_CJK_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]
_NUM = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
_LAT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_LATB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def _first_existing(paths: List[str]) -> Optional[str]:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _rel_time(ts: Optional[datetime]) -> str:
    if ts is None:
        return "—"
    now = datetime.now(timezone.utc)
    sec = int((now - ts).total_seconds())
    if sec < 0:
        sec = 0
    if sec < 60:
        return "刚刚"
    if sec < 3600:
        return f"{sec // 60} 分钟前"
    if sec < 86400:
        return f"{sec // 3600} 小时前"
    return f"{sec // 86400} 天前"


def _fmt(v: Optional[float], unit: str, digits: int = 1) -> str:
    if v is None:
        return f"--{unit}"
    return f"{v:.{digits}f}{unit}"


def _arc_points(cx: float, cy: float, r: float, a0: float, a1: float, steps: int):
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _arc_band(surf, color, cx, cy, r_in, r_out, a0, a1, steps=150):
    outer = _arc_points(cx, cy, r_out, a0, a1, steps)
    inner = _arc_points(cx, cy, r_in, a1, a0, steps)
    poly = [(int(x), int(y)) for x, y in outer + inner]
    if len(poly) >= 3:
        pygame.draw.polygon(surf, color, poly)
    rc = (r_in + r_out) / 2
    rr = int((r_out - r_in) / 2)
    for ang in (a0, a1):
        rad = math.radians(ang)
        pygame.draw.circle(surf, color, (int(cx + rc * math.cos(rad)),
                                         int(cy + rc * math.sin(rad))), rr)


def _hexagon(cx, cy, r, pointy_top=True):
    pts = []
    for i in range(6):
        a = math.radians(90 + 60 * i if pointy_top else 60 * i)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return [(int(x), int(y)) for x, y in pts]


def _build_vignette(w, h, strength=155):
    sw, sh = 64, 40
    v = pygame.Surface((sw, sh), pygame.SRCALPHA)
    cx, cy = sw / 2 - 0.5, sh / 2 - 0.5
    maxd = math.hypot(cx, cy)
    for y in range(sh):
        for x in range(sw):
            d = math.hypot(x - cx, y - cy) / maxd
            a = int(strength * max(0.0, d - 0.5) / 0.5)
            v.set_at((x, y), (0, 0, 0, min(strength, max(0, a))))
    return pygame.transform.smoothscale(v, (w, h))


def _build_background(w, h):
    bg = pygame.Surface((w, h))
    bg.fill(BG)
    grid = pygame.Surface((w, h), pygame.SRCALPHA)
    hex_r = 74.0
    dx = hex_r * 1.5
    dy = hex_r * math.sqrt(3)
    col = 0
    x = -hex_r
    while x < w + hex_r * 2:
        y = 0 if col % 2 == 0 else dy / 2
        while y < h + hex_r * 2:
            pygame.draw.polygon(grid, (255, 255, 255, 7), _hexagon(x, y, hex_r), 1)
            y += dy
        x += dx
        col += 1
    bg.blit(grid, (0, 0))
    bg.blit(_build_vignette(w, h), (0, 0))
    return bg


class Renderer:
    def __init__(self, cfg: EdgeConfig):
        self.cjk = _first_existing([cfg.font_path] + _CJK_CANDIDATES)
        if not self.cjk:
            log.warning("未找到 CJK 字体，中文可能显示为方块（请安装 fonts-noto-cjk）")
        self._cache = {}
        self.base = pygame.Surface((DW, DH))
        self.bg = _build_background(DW, DH)

    def font(self, kind: str, size: int, bold: bool = False):
        key = (kind, size, bold)
        f = self._cache.get(key)
        if f is None:
            path = {
                "cjk": self.cjk,
                "num": _first_existing([_NUM]),
                "lat": _first_existing([_LAT]),
                "latb": _first_existing([_LATB]),
                "mono": _first_existing([_MONO]),
            }.get(kind)
            if path:
                f = pygame.font.Font(path, size)
            else:
                f = pygame.font.SysFont(None, size, bold=bold)
            self._cache[key] = f
        return f

    # -- 绘制辅助 --
    def text(self, surf, s, font, color, *, center=None, midleft=None,
             midright=None, topleft=None, topright=None, midtop=None,
             midbottom=None):
        img = font.render(s, True, color)
        r = img.get_rect()
        if center is not None:
            r.center = center
        elif midleft is not None:
            r.midleft = midleft
        elif midright is not None:
            r.midright = midright
        elif topleft is not None:
            r.topleft = topleft
        elif topright is not None:
            r.topright = topright
        elif midtop is not None:
            r.midtop = midtop
        elif midbottom is not None:
            r.midbottom = midbottom
        surf.blit(img, r)
        return r

    def render(self, cfg: EdgeConfig, state: dict):
        s = self.base
        s.blit(self.bg, (0, 0))

        # 顶栏 / 底栏分隔线（左侧蜂蜜金引导段）
        for y in (126, 688):
            pygame.draw.line(s, LINE, (46, y), (DW - 46, y), 1)
            pygame.draw.line(s, HONEY, (46, y), (166, y), 3)

        # ── 顶栏 · 身份 ─────────────────────────────────
        glow = pygame.Surface((100, 100), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*HONEY, 36), (50, 50), 46)
        s.blit(glow, (86 - 50, 74 - 50))
        pygame.draw.polygon(s, HONEY, _hexagon(86, 74, 30), 4)
        pygame.draw.polygon(s, HONEY, _hexagon(86, 74, 14))

        name = str(state.get("device_name", cfg.device_name))
        self.text(s, name, self.font("num", 48), TEXT, midleft=(142, 60))
        self.text(s, "智能蜂箱监测", self.font("cjk", 22), DIM, midleft=(144, 98))

        # ── 顶栏 · 时钟 / 网络 ──────────────────────────
        self._clock_layer(s)

        # ── 核心：失王概率环形仪表盘 ────────────────────
        gx, gy = 392, 428
        r_out, r_in = 208, 180
        tone = TONE.get(state.get("tone", "neutral"), TONE["neutral"])
        p = state.get("probability_no_queen")
        updating = bool(state.get("updating"))

        a0, sweep = 125.0, 290.0
        a1 = a0 + sweep
        _arc_band(s, PANEL_HI, gx, gy, r_in, r_out, a0, a1)
        if not updating and p is not None:
            pf = max(0.0, min(1.0, float(p)))
            _arc_band(s, tone, gx, gy, r_in, r_out, a0, a0 + sweep * pf)
        # 刻度
        for k in range(11):
            ang = math.radians(a0 + sweep * k / 10)
            x1 = gx + (r_out + 8) * math.cos(ang)
            y1 = gy + (r_out + 8) * math.sin(ang)
            x2 = gx + (r_out + 18) * math.cos(ang)
            y2 = gy + (r_out + 18) * math.sin(ang)
            pygame.draw.line(s, LINE if k % 5 else DIM, (x1, y1), (x2, y2), 2)

        if updating:
            # 采集模式：模型更新中，暂不显示失王概率
            self.text(s, "蜂王判断", self.font("cjk", 30), DIM, center=(gx, gy - 96))
            self.text(s, "判断模型正在更新", self.font("cjk", 40), TEXT,
                      center=(gx, gy + 4))
            self.text(s, "数据采集中", self.font("cjk", 34, bold=True), HONEY,
                      center=(gx, gy + 118))
        else:
            self.text(s, "失王概率", self.font("cjk", 30), DIM, center=(gx, gy - 96))
            # 大数字 + %
            if p is None:
                num_img = self.font("num", 128).render("—", True, tone)
                nrect = num_img.get_rect(center=(gx, gy + 4))
                s.blit(num_img, nrect)
            else:
                num = f"{float(p) * 100:.1f}"
                fnum = self.font("num", 128)
                img = fnum.render(num, True, tone)
                pct = self.font("num", 54).render("%", True, tone)
                gap = 8
                total = img.get_width() + gap + pct.get_width()
                x0 = gx - total // 2
                s.blit(img, (x0, gy + 4 - img.get_height() // 2))
                s.blit(pct, (x0 + img.get_width() + gap,
                             gy + 4 - pct.get_height() // 2 + 16))
            status = str(state.get("status", "等待数据"))
            self.text(s, status, self.font("cjk", 34, bold=True), tone,
                      center=(gx, gy + 118))

        # ── 右侧：温湿度卡片 ────────────────────────────
        self._card(s, 748, 150, 486, 196, "温度", "TEMPERATURE",
                   _fmt(state.get("temperature"), ""), "℃", HONEY)
        self._card(s, 748, 362, 486, 196, "湿度", "HUMIDITY",
                   _fmt(state.get("humidity"), ""), "%", TEAL)

        # ── 模型信息条 ──────────────────────────────────
        mv = str(state.get("model_version", "—"))
        cycle = state.get("cycle_ms")
        cyc = f"{float(cycle) / 1000:.1f}s" if cycle else "—"
        pygame.draw.rect(s, PANEL, pygame.Rect(748, 574, 486, 92), border_radius=18)
        pygame.draw.rect(s, LINE, pygame.Rect(748, 574, 486, 92), 1, border_radius=18)
        self.text(s, "模型", self.font("cjk", 24), DIM, midleft=(776, 606))
        self.text(s, mv, self.font("lat", 24), TEXT, midleft=(836, 606))
        self.text(s, "采集周期", self.font("cjk", 22), DIM, midleft=(776, 644))
        self.text(s, cyc, self.font("lat", 22), TEXT, midleft=(896, 644))

        # ── 底栏 ────────────────────────────────────────
        ts = _parse_iso(state.get("updated_at"))
        stale = ts is not None and (datetime.now(timezone.utc) - ts).total_seconds() > cfg.normal_interval_s * 2.5
        rel = _rel_time(ts)
        abs_t = ts.astimezone().strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
        r = self.text(s, "更新于 " + rel, self.font("cjk", 24),
                      TONE["warn"] if stale else DIM, midleft=(46, 727))
        self.text(s, "· " + abs_t, self.font("lat", 22), FAINT,
                  midleft=(r.right + 16, 727))

        synced = bool(state.get("synced", False))
        dot = TONE["ok"] if synced else TONE["warn"]
        label = "已同步云端" if synced else "本地缓存"
        r = self.text(s, label, self.font("cjk", 24), DIM, midright=(DW - 46, 727))
        pygame.draw.circle(s, dot, (r.left - 20, r.centery), 7)

        # 四角仪器框
        for ox, oy, sx, sy in ((24, 24, 1, 1), (DW - 24, 24, -1, 1),
                               (24, DH - 24, 1, -1), (DW - 24, DH - 24, -1, -1)):
            pygame.draw.line(s, LINE, (ox, oy), (ox + 28 * sx, oy), 3)
            pygame.draw.line(s, LINE, (ox, oy), (ox, oy + 28 * sy), 3)

    def _clock_layer(self, s) -> None:
        # 区域内含分隔线段，重绘以支持每秒局刷
        pygame.draw.line(s, LINE, (760, 126), (DW - 46, 126), 1)
        now = datetime.now()
        self.text(s, now.strftime("%H:%M:%S"), self.font("mono", 46), TEXT,
                  midright=(DW - 46, 58))
        self.text(s, now.strftime("%Y-%m-%d  %a"), self.font("lat", 21), DIM,
                  midright=(DW - 46, 96))
        ips = ipv4_addresses()
        net = hostname()
        if ips:
            net += f" · {ips[0]}"
        self.text(s, net, self.font("lat", 21), FAINT, midright=(DW - 46, 122))

    def draw_clock(self) -> None:
        self.base.blit(self.bg, CLOCK_RECT, CLOCK_RECT)
        self._clock_layer(self.base)

    def present(self, screen) -> None:
        w, h = screen.get_size()
        if (w, h) != (DW, DH):
            screen.blit(pygame.transform.smoothscale(self.base, (w, h)), (0, 0))
        else:
            screen.blit(self.base, (0, 0))

    def draw(self, screen, cfg: EdgeConfig, state: dict) -> None:
        self.render(cfg, state)
        self.present(screen)

    def _card(self, s, x, y, w, h, label_cn, label_en, value, unit, accent):
        pygame.draw.rect(s, PANEL, pygame.Rect(x, y, w, h), border_radius=20)
        pygame.draw.rect(s, LINE, pygame.Rect(x, y, w, h), 1, border_radius=20)
        pygame.draw.rect(s, accent, pygame.Rect(x + 22, y + 30, 6, h - 60),
                         border_radius=3)
        self.text(s, label_cn, self.font("cjk", 30), DIM, midleft=(x + 48, y + 40))
        self.text(s, label_en, self.font("lat", 15), FAINT,
                  midright=(x + w - 26, y + 42))
        self.text(s, value, self.font("num", 96), TEXT, midleft=(x + 44, y + 120))
        vr = self.font("num", 96).size(value)
        self.text(s, unit, self.font("cjk", 40), accent,
                  midleft=(x + 52 + vr[0], y + 124))


def run_display(cfg: EdgeConfig) -> None:
    if pygame is None:
        raise RuntimeError("显示模式需要 pygame（pip install pygame）")

    width, height = cfg.display_width, cfg.display_height
    screen = None
    renderer = None

    while True:
        if screen is None:
            try:
                pygame.display.init()
                pygame.font.init()
                flags = pygame.FULLSCREEN
                if width and height:
                    screen = pygame.display.set_mode((width, height), flags)
                else:
                    screen = pygame.display.set_mode((0, 0), flags)
                pygame.mouse.set_visible(False)
                renderer = Renderer(cfg)
                log.info("显示初始化成功：%s", screen.get_size())
            except Exception as e:  # noqa: BLE001
                log.warning("显示初始化失败（无 HDMI？），5s 后重试：%s", e)
                time.sleep(5)
                continue

        last_sig = None
        while screen is not None:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    return

            state = read_state(cfg.state_file) or {}
            sig = repr(state)
            try:
                if sig != last_sig:          # 数据变化 → 整屏重绘
                    renderer.render(cfg, state)
                    last_sig = sig
                renderer.draw_clock()        # 每秒局刷时钟 → 连续走秒
                renderer.present(screen)
                pygame.display.flip()
            except Exception as e:  # noqa: BLE001
                log.warning("渲染失败，5s 后重试：%s", e)
                screen = None
                renderer = None
                time.sleep(5)
                break

            # 对齐到整秒，使读数平滑跳动
            time.sleep(max(0.05, 1.0 - (time.monotonic() % 1.0)))
