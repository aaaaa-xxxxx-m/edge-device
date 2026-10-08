#!/usr/bin/env python3
"""边缘设备入口。

用法：
  python main.py --config config.toml --mode edge      # 采集+推理+上传
  python main.py --config config.toml --mode display   # HDMI 状态显示
"""
from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="智能蜂箱 · 边缘设备")
    parser.add_argument("--config", default="config.toml", help="配置文件路径")
    parser.add_argument("--mode", choices=["edge", "display"], default="edge")
    args = parser.parse_args()

    from bee_edge.config import load_config

    cfg = load_config(args.config)
    _setup_logging(cfg.log_level)

    if args.mode == "edge":
        from bee_edge.app import EdgeApp

        EdgeApp(cfg).run()
    else:
        from bee_edge.display import run_display

        run_display(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
