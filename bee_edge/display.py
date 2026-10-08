"""HDMI 显示屏渲染（pygame，纯本地、离线可用）。

读取 state.json，全屏展示：设备名 / 温度 / 湿度 / 失王概率 + 状态 + 更新时间。
运行在控制台（无 X）时使用 SDL 的 kmsdrm/fb 驱动。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

from .config import EdgeConfig
from .netinfo import hostname, ipv4_addresses
from .state import read_state

log = logging.getLogger("bee_edge.display")

REFRESH_S = 5.0

# 背景/文字
BG = (14, 23, 18)
FG = (233, 240, 234)
MUTED = (140, 158, 146)
CARD = (23, 35, 29)
TONE = {
    "ok": (46, 190, 120),
    "warn": (232, 161, 58),
    "danger": (224, 74, 74),
    "neutral": (150, 160, 152),
}


def _find_font(explicit: str) -> Optional[str]:
    candidates = [
        explicit,
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
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


def run_display(cfg: EdgeConfig) -> None:
    import pygame

    font_path = _find_font(cfg.font_path)
    if not font_path:
        log.warning("未找到 CJK 字体，中文可能显示为方块（请安装 fonts-noto-cjk）")

    width, height = cfg.display_width, cfg.display_height
    screen = None

    while True:
        # 确保显示可用（无 HDMI 时重试，不崩溃）
        if screen is None:
            try:
                pygame.display.init()
                flags = pygame.FULLSCREEN
                if width and height:
                    screen = pygame.display.set_mode((width, height), flags)
                else:
                    screen = pygame.display.set_mode((0, 0), flags)
                pygame.mouse.set_visible(False)
                log.info("显示初始化成功：%s", screen.get_size())
            except Exception as e:  # noqa: BLE001
                log.warning("显示初始化失败（无 HDMI？），5s 后重试：%s", e)
                time.sleep(5)
                continue

        w, h = screen.get_size()

        def font(frac: float, bold: bool = False):
            size = max(12, int(h * frac))
            if font_path:
                return pygame.font.Font(font_path, size)
            return pygame.font.SysFont(None, size, bold=bold)

        f_name = font(0.075)
        f_big = font(0.16, bold=True)
        f_prob = font(0.22, bold=True)
        f_status = font(0.09, bold=True)
        f_small = font(0.038)

        state = read_state(cfg.state_file) or {}

        def draw_text(surf, text, f, color, center=None, topleft=None):
            img = f.render(text, True, color)
            rect = img.get_rect()
            if center:
                rect.center = center
            elif topleft:
                rect.topleft = topleft
            surf.blit(img, rect)
            return rect

        # 事件
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return

        screen.fill(BG)

        name = state.get("device_name", cfg.device_name)
        draw_text(screen, str(name), f_name, FG, center=(w // 2, int(h * 0.08)))

        # 温度 / 湿度
        temp = _fmt(state.get("temperature"), "℃")
        humi = _fmt(state.get("humidity"), "%")
        draw_text(screen, "温度", f_small, MUTED, center=(int(w * 0.27), int(h * 0.22)))
        draw_text(screen, temp, f_big, FG, center=(int(w * 0.27), int(h * 0.31)))
        draw_text(screen, "湿度", f_small, MUTED, center=(int(w * 0.73), int(h * 0.22)))
        draw_text(screen, humi, f_big, FG, center=(int(w * 0.73), int(h * 0.31)))

        # 失王概率
        p = state.get("probability_no_queen")
        tone = TONE.get(state.get("tone", "neutral"), TONE["neutral"])
        draw_text(screen, "失王概率", f_small, MUTED, center=(w // 2, int(h * 0.46)))
        p_text = "—" if p is None else f"{p * 100:.1f}%"
        draw_text(screen, p_text, f_prob, tone, center=(w // 2, int(h * 0.57)))

        # 概率条
        bar_w, bar_h = int(w * 0.6), max(10, int(h * 0.02))
        bx, by = (w - bar_w) // 2, int(h * 0.68)
        pygame.draw.rect(screen, CARD, pygame.Rect(bx, by, bar_w, bar_h), border_radius=bar_h // 2)
        if p is not None:
            fill = max(0, min(bar_w, int(bar_w * float(p))))
            pygame.draw.rect(screen, tone, pygame.Rect(bx, by, fill, bar_h), border_radius=bar_h // 2)

        # 状态
        draw_text(screen, str(state.get("status", "等待数据")), f_status, tone, center=(w // 2, int(h * 0.79)))

        # 更新时间 + 模式
        ts = _parse_iso(state.get("updated_at"))
        rel = _rel_time(ts)
        abs_t = ts.astimezone().strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
        stale = ts is not None and (datetime.now(timezone.utc) - ts).total_seconds() > cfg.normal_interval_s * 2.5
        info = f"更新：{rel}（{abs_t}）" + ("" if state.get("synced", False) else " · 本地")
        draw_text(screen, info, f_small, TONE["warn"] if stale else MUTED, center=(w // 2, int(h * 0.92)))

        # 左上角显示主机名 + IP（方便手机连接）
        ips = ipv4_addresses()
        if ips:
            draw_text(screen, f"{hostname()} · {ips[0]}", f_small, MUTED,
                      topleft=(int(w * 0.02), int(h * 0.02)))

        pygame.display.flip()
        time.sleep(REFRESH_S)
