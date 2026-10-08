"""本地网页配置（在树莓派上开一个小页面，手机/电脑浏览器填写设备名与密钥）。

仅监听局域网，提交后联网校验并写入 config.toml；可选访问口令（--setup-token）。

用法：
    python main.py --mode websetup [--host 0.0.0.0] [--port 8080] [--setup-token 123456]
    浏览器打开 http://<树莓派IP>:8080/  （若设了口令：http://<ip>:8080/?t=123456）
"""
from __future__ import annotations

import html
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .server import AuthError, ServerClient, ServerError
from .setup import DEFAULT_SERVER, _write_config

_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>边缘设备配置</title>
<style>
 body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;
      background:#0e1712;color:#e9f0ea;display:flex;justify-content:center;padding:24px}}
 .card{{width:100%;max-width:460px;background:#17231d;border:1px solid #24352b;
        border-radius:16px;padding:24px}}
 h1{{font-size:20px;margin:0 0 6px}} .sub{{color:#8c9e92;font-size:13px;margin:0 0 18px}}
 label{{display:block;font-size:13px;color:#b9c8bd;margin:14px 0 6px}}
 input{{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;
        border:1px solid #2f4437;background:#0f1a14;color:#e9f0ea;font-size:15px}}
 button{{margin-top:20px;width:100%;padding:13px;border:none;border-radius:10px;
         background:#2ebe78;color:#04140b;font-size:16px;font-weight:700}}
 .msg{{margin-top:16px;padding:12px 14px;border-radius:10px;font-size:14px}}
 .ok{{background:#12351f;color:#4fe08c}} .err{{background:#3a1717;color:#f08a8a}}
 .tip{{color:#8c9e92;font-size:12px;margin-top:14px;line-height:1.6}}
</style></head>
<body><div class="card">
 <h1>边缘设备配置</h1>
 <p class="sub">填写云端注册设备时获得的设备名与 API Key。提交后会联网校验并保存。</p>
 {msg}
 <form method="post" action="save{qs}">
  <label>服务器地址</label>
  <input name="server" value="{server}">
  <label>设备名 (device_name)</label>
  <input name="device_name" value="{device_name}" placeholder="如 hive001">
  <label>设备 API Key</label>
  <input name="api_key" value="{api_key}" placeholder="bee_..." autocomplete="off">
  <button type="submit">保存并校验</button>
 </form>
 <p class="tip">配置将写入：{config_path}<br>仅局域网可访问。保存成功后，回到树莓派启用服务：
  <code>sudo systemctl enable --now bee-edge bee-display</code></p>
</div></body></html>"""


def _read_existing(path: str) -> dict:
    out = {"device_name": "", "api_key": "", "server_base_url": DEFAULT_SERVER}
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return out
    for key in out:
        m = re.search(rf'(?m)^{re.escape(key)}\s*=\s*"([^"]*)"', text)
        if m:
            out[key] = m.group(1)
    return out


def _render(config_path: str, token: str, msg: str = "") -> bytes:
    cur = _read_existing(config_path)
    page = _PAGE.format(
        msg=msg,
        qs=(f"?t={html.escape(token)}" if token else ""),
        server=html.escape(cur["server_base_url"]),
        device_name=html.escape(cur["device_name"]),
        api_key=html.escape(cur["api_key"]),
        config_path=html.escape(os.path.abspath(config_path)),
    )
    return page.encode("utf-8")


def run_websetup(config_path: str, host: str, port: int, token: str) -> int:
    def make_handler():
        class Handler(BaseHTTPRequestHandler):
            def _ok_auth(self) -> bool:
                if not token:
                    return True
                qs = parse_qs(urlparse(self.path).query)
                return qs.get("t", [None])[0] == token

            def _send(self, body: bytes, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                if not self._ok_auth():
                    self._send("<h3>403 需要口令：在网址后加 ?t=口令</h3>".encode(), 403)
                    return
                self._send(_render(config_path, token))

            def do_POST(self):  # noqa: N802
                if not self._ok_auth():
                    self._send(b"403", 403)
                    return
                if urlparse(self.path).path != "/save":
                    self._send(b"404", 404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                server = (form.get("server", [DEFAULT_SERVER])[0] or DEFAULT_SERVER).strip()
                device_name = (form.get("device_name", [""])[0] or "").strip()
                api_key = (form.get("api_key", [""])[0] or "").strip()

                if not device_name or not api_key:
                    msg = '<div class="msg err">设备名与 API Key 均不能为空</div>'
                    self._send(_render(config_path, token, msg))
                    return
                try:
                    st = ServerClient(server, api_key, timeout=15.0).get_model_status(device_name)
                    _write_config(config_path, device_name, api_key, server)
                    msg = (f'<div class="msg ok">配置成功！设备「{html.escape(device_name)}」'
                           f'校验通过（状态 {html.escape(str(st.get("status", "?")))}），已保存。</div>')
                except AuthError as e:
                    msg = f'<div class="msg err">校验失败：密钥无效 / 设备不存在 / 名称不匹配（{html.escape(str(e))}）</div>'
                except ServerError as e:
                    msg = f'<div class="msg err">无法连接服务器：请检查网络与服务器地址（{html.escape(str(e))}）</div>'
                self._send(_render(config_path, token, msg))

            def log_message(self, *a):  # 静默
                pass

        return Handler

    server = ThreadingHTTPServer((host, port), make_handler())
    print("== 网页配置模式 ==")
    print(f"监听：http://{host}:{port}/" + (f"  （口令 --setup-token {token}）" if token else ""))
    print(f"配置文件：{os.path.abspath(config_path)}")
    print("在同一局域网的手机/电脑浏览器打开上面的地址填写即可。Ctrl+C 退出。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        server.server_close()
    return 0
