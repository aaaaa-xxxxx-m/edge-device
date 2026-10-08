"""在全屏上显示本机 IP（方便手机连接配置页）。无需 config。

用法：python main.py --mode showip [--port 8080]
"""
from __future__ import annotations

import logging
import time

from .netinfo import hostname, ipv4_addresses

log = logging.getLogger("bee_edge.showip")

BG = (14, 23, 18)
FG = (233, 240, 234)
MUTED = (140, 158, 146)
ACCENT = (46, 190, 120)


def run_showip(port: int = 8080) -> None:
    import pygame

    from .display import _find_font

    font_path = _find_font("")
    screen = None

    while True:
        if screen is None:
            try:
                pygame.display.init()
                screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                pygame.mouse.set_visible(False)
            except Exception as e:  # noqa: BLE001
                log.warning("显示初始化失败（无 HDMI？），5s 后重试：%s", e)
                time.sleep(5)
                continue

        w, h = screen.get_size()

        def font(frac: float, bold: bool = False):
            size = max(12, int(h * frac))
            return pygame.font.Font(font_path, size) if font_path else pygame.font.SysFont(None, size, bold=bold)

        f_small = font(0.045)
        f_host = font(0.075)
        f_ip = font(0.13, bold=True)
        f_hint = font(0.05)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return

        screen.fill(BG)
        ips = ipv4_addresses()
        primary = ips[0] if ips else "127.0.0.1"

        def center(text, f, color, y):
            img = f.render(text, True, color)
            rect = img.get_rect(center=(w // 2, int(h * y)))
            screen.blit(img, rect)

        center("本机 IP 地址", f_small, MUTED, 0.13)
        center(f"主机名：{hostname()}", f_host, FG, 0.23)
        center(primary, f_ip, ACCENT, 0.42)
        if len(ips) > 1:
            center("其它：" + "  ".join(ips[1:]), f_small, MUTED, 0.53)
        center(f"手机浏览器打开：http://{primary}:{port}/", f_hint, FG, 0.66)
        center("（同一局域网内）", f_small, MUTED, 0.73)

        pygame.display.flip()
        time.sleep(3)
