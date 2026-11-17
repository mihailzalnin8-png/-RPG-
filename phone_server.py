# -*- coding: utf-8 -*-
"""Мобильный режим для текстовой RPG.

Что делает:
- поднимает локальный HTTP-сервер (по умолчанию порт 8000);
- отдаёт мобильную страницу-терминал: вывод игры + поле ввода;
- рисует QR-код в консоли и отдаёт большой QR в браузере;
- запускает игру в отдельном потоке, а print()/input() игры направляет
  в очередь конкретной телефонной сессии.

Как подключить к игре (см. install_phone.py, он делает это автоматически):

    import phone_server

    def print(*args, **kwargs):
        sess = phone_server.current_session() if phone_server else None
        ...

    def input(prompt=""):
        sess = phone_server.current_session() if phone_server else None
        ...

    # в меню игры:
    phone_server.phone_menu(main)

Модуль не обязателен для обычной игры на ПК: если qrcode не установлен,
сервер всё равно работает, просто QR придётся открыть в браузере.
"""

from __future__ import annotations

import io
import json
import os
import queue
import secrets
import socket
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Состояние
# ---------------------------------------------------------------------------

_local = threading.local()

_lock = threading.Lock()
_server = None
_server_thread = None
_port = 0
_game_main = None

_sessions = {}      # token -> GameSession
_by_client = {}     # client_id -> GameSession
_active = None      # сейчас играет только одна телефонная сессия

_qr_cache = {}

MAX_TEXT = 400_000
DEFAULT_PORTS = range(8000, 8030)


def current_session():
    """Сессия телефона для текущего потока (или None для обычной консоли)."""
    return getattr(_local, "session", None)


class GameSession:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.text = ""
        self.clear_seq = 0
        self.inputs: queue.Queue[str] = queue.Queue()
        self.waiting = 0
        self.closed = False
        self.thread = None
        self.last_seen = time.monotonic()

    # -- вывод ------------------------------------------------------------
    def write(self, text: str):
        if text is None:
            text = ""
        text = str(text)
        with self.lock:
            self.text += text
            if len(self.text) > MAX_TEXT:
                self.text = self.text[-MAX_TEXT:]
                self.clear_seq += 1

    def clear(self):
        with self.lock:
            self.text = ""
            self.clear_seq += 1

    # -- ввод -------------------------------------------------------------
    def read(self) -> str:
        with self.lock:
            self.waiting += 1
        try:
            return self.inputs.get()
        finally:
            with self.lock:
                self.waiting = max(0, self.waiting - 1)

    def submit(self, text: str):
        self.inputs.put(text)

    # -- состояние --------------------------------------------------------
    def is_closed(self) -> bool:
        with self.lock:
            return self.closed

    def snapshot(self, since: int, client_clear_seq: int):
        with self.lock:
            reset = client_clear_seq != self.clear_seq or since < 0 or since > len(self.text)
            if reset:
                text = self.text
            else:
                text = self.text[since:]
            return {
                "text": text,
                "since": len(self.text),
                "clear_seq": self.clear_seq,
                "reset": reset,
                "input": self.waiting > 0,
                "closed": self.closed,
            }


# ---------------------------------------------------------------------------
# IP и QR
# ---------------------------------------------------------------------------

def _primary_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def phone_url() -> str:
    return f"http://{_primary_ip()}:{_port}/"


def _qr_matrix(data: str):
    try:
        import qrcode
    except Exception:
        return None
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_ansi_lines(data: str):
    """QR половинными блоками: 1 знакоместо = 1 модуль (квадратные модули)."""
    matrix = _qr_matrix(data)
    if not matrix:
        return None
    if len(matrix) % 2:
        matrix = matrix + [[False] * len(matrix[0])]

    lines = []
    for y in range(0, len(matrix), 2):
        row = []
        for x in range(len(matrix[y])):
            top = matrix[y][x]
            bottom = matrix[y + 1][x]
            fg = "30" if top else "97"          # верхняя половина: чёрный / белый
            bg = "40" if bottom else "107"      # нижняя половина: чёрный / белый
            row.append(f"\x1b[{fg};{bg}m▀")
        row.append("\x1b[0m")
        lines.append("".join(row))
    return lines


def _enable_ansi():
    """Включает VT-последовательности в консоли Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _qr_svg_bytes(data: str):
    try:
        import qrcode
        import qrcode.image.svg
    except Exception:
        return None
    key = ("svg", data)
    if key in _qr_cache:
        return _qr_cache[key]
    img = qrcode.make(
        data,
        image_factory=qrcode.image.svg.SvgPathImage,
        border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    buf = io.BytesIO()
    img.save(buf)
    value = buf.getvalue()
    _qr_cache[key] = value
    return value


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

MOBILE_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#111a22">
<title>Текстовая RPG</title>
<style>
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:#0b1016;color:#d8e2ea;font-family:ui-monospace,Consolas,"Courier New",monospace;
       display:flex;flex-direction:column;height:100dvh;overflow:hidden}
  header{display:flex;align-items:center;gap:10px;padding:9px 12px;background:#111a22;
         border-bottom:1px solid #22303c;flex:0 0 auto;font-weight:700;font-size:14px}
  header .title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #status{font-size:11px;font-weight:400;white-space:nowrap}
  #status.ok{color:#4ade80}
  #status.bad{color:#f87171}
  #reload{background:#1d2a35;color:#d8e2ea;padding:5px 10px;font-size:15px}
  #main{flex:1 1 auto;overflow-y:auto;padding:10px 12px 18px;-webkit-overflow-scrolling:touch}
  #out{margin:0;white-space:pre-wrap;word-break:break-word;font:15px/1.35 ui-monospace,Consolas,"Courier New",monospace;color:#d8e2ea}
  #quick{flex:0 0 auto;display:flex;gap:6px;padding:6px 10px;overflow-x:auto;background:#0e151c;
         border-top:1px solid #1a2530;scrollbar-width:none}
  #quick::-webkit-scrollbar{display:none}
  #quick button{flex:0 0 auto;background:#1d2a35;color:#d8e2ea;padding:7px 12px;font-size:14px;font-weight:600}
  #bar{flex:0 0 auto;display:flex;gap:8px;padding:8px 10px calc(8px + env(safe-area-inset-bottom));
       background:#111a22;border-top:1px solid #22303c}
  #cmd{flex:1;min-width:0;font-size:16px;padding:11px 12px;border-radius:10px;border:1px solid #2c3e4c;
       background:#0b1016;color:#fff;outline:none}
  #cmd:focus{border-color:#e2b13c}
  button{font:inherit;border:0;border-radius:10px;background:#e2b13c;color:#17120a;padding:11px 16px;font-weight:700;cursor:pointer}
  button:active{transform:translateY(1px)}
  button:disabled{opacity:.4;cursor:default;transform:none}
</style>
</head>
<body>
<header>
  <span class="title">⚔️ ТЕКСТОВАЯ RPG</span>
  <span id="status" class="bad">●</span>
  <button id="reload" title="Перезагрузить">⟳</button>
</header>
<main id="main"><pre id="out">Подключение...</pre></main>
<div id="quick">
  <button data-v="1">1</button><button data-v="2">2</button><button data-v="3">3</button>
  <button data-v="4">4</button><button data-v="5">5</button><button data-v="6">6</button>
  <button data-v="7">7</button><button data-v="8">8</button><button data-v="9">9</button>
  <button data-v="0">0</button><button data-v="y">y</button><button data-v="n">n</button>
  <button data-v="все">все</button>
</div>
<form id="bar">
  <input id="cmd" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Введи ответ…">
  <button id="send" type="submit" disabled>➤</button>
</form>
<script>
(function () {
  var out = document.getElementById('out');
  var main = document.getElementById('main');
  var cmd = document.getElementById('cmd');
  var form = document.getElementById('bar');
  var statusEl = document.getElementById('status');
  var token = null;
  var since = 0;
  var clearSeq = -1;
  var gameOver = false;
  var awaiting = false;
  var lastInput = false;
  var busy = false;
  var polling = false;
  var started = false;
  var timer = null;
  var sendBtn = document.getElementById('send');

  var client = localStorage.getItem('rpg_client');
  if (!client) {
    client = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
             : ('c' + Date.now() + Math.random().toString(16).slice(2));
    localStorage.setItem('rpg_client', client);
  }

  function setStatus(ok, text) {
    statusEl.textContent = text || (ok ? '● онлайн' : '● нет связи');
    statusEl.className = ok ? 'ok' : 'bad';
  }

  function updateInputState() {
    var enabled = !!token && !gameOver && awaiting;
    sendBtn.disabled = !enabled;
    if (gameOver) {
      cmd.placeholder = 'Игра завершена';
    } else if (awaiting) {
      cmd.placeholder = 'Введи ответ…';
    } else {
      cmd.placeholder = 'Игра печатает…';
    }
  }

  function autoScroll() {
    var near = main.scrollHeight - main.scrollTop - main.clientHeight < 180;
    if (near) main.scrollTop = main.scrollHeight;
  }

  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(poll, ms);
  }

  async function api(path, opts) {
    var r = await fetch(path, opts || {});
    if (!r.ok) {
      var t = await r.text();
      throw new Error(t || ('HTTP ' + r.status));
    }
    return r.json();
  }

  async function start() {
    try {
      var d = await api('/api/new?client=' + encodeURIComponent(client));
      token = d.token;
      since = d.since;
      clearSeq = d.clear_seq;
      out.textContent = d.text || '';
      awaiting = !!d.input;
      started = true;
      updateInputState();
      setStatus(true);
      autoScroll();
      schedule(80);
    } catch (e) {
      out.textContent = '❌ ' + e.message;
      setStatus(false, '● ошибка');
    }
  }

  async function poll() {
    if (!token || gameOver || polling) return;
    polling = true;
    var delay = 350;
    try {
      var d = await api('/api/poll?token=' + encodeURIComponent(token) +
                        '&since=' + encodeURIComponent(since) +
                        '&clear=' + encodeURIComponent(clearSeq));
      if (d.reset) {
        out.textContent = d.text;
      } else if (d.text) {
        out.textContent += d.text;
      }
      since = d.since;
      clearSeq = d.clear_seq;
      gameOver = d.closed;
      awaiting = !!d.input;
      updateInputState();
      setStatus(!d.closed);
      if (d.input && !lastInput && !gameOver) {
        try { cmd.focus(); } catch (e) {}
      }
      lastInput = d.input;
      autoScroll();
    } catch (e) {
      setStatus(false, '● нет связи');
      delay = 1500;
    } finally {
      polling = false;
    }
    if (!gameOver) schedule(delay);
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (!token || gameOver || busy || !awaiting) return;
    var text = cmd.value;
    busy = true;
    try {
      var r = await fetch('/api/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: token, text: text})
      });
      if (!r.ok) throw new Error(await r.text());
      cmd.value = '';
      awaiting = false;
      updateInputState();
      lastInput = false;
      schedule(30);
    } catch (e) {
      setStatus(false, '● ошибка');
    } finally {
      busy = false;
    }
  });

  document.querySelectorAll('#quick button').forEach(function (b) {
    b.addEventListener('click', function () {
      cmd.value += b.dataset.v;
      try { cmd.focus(); } catch (e) {}
    });
  });

  document.getElementById('reload').addEventListener('click', function () {
    location.reload();
  });

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && started && !gameOver) schedule(50);
  });

  start();
})();
</script>
</body>
</html>
"""


def _qr_page_html() -> str:
    url = phone_url()
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>QR — Текстовая RPG</title><style>"
        "body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;"
        "justify-content:center;background:#fff;color:#111;font-family:system-ui,Segoe UI,Arial,sans-serif;text-align:center}"
        "h1{font-size:24px;margin:14px 16px}img{width:min(78vmin,520px);height:auto;image-rendering:pixelated}"
        "code{font-size:17px;background:#f0f0f0;padding:8px 12px;border-radius:8px;display:inline-block;margin:8px;word-break:break-all}"
        "p{max-width:660px;margin:6px 18px;color:#444;font-size:15px;line-height:1.45}"
        "</style></head><body>"
        "<h1>📱 Наведи камеру телефона</h1>"
        "<img src='/qr.svg' alt='QR-код'>"
        f"<p>Адрес: <code>{url}</code></p>"
        "<p>Телефон должен быть в той же Wi-Fi сети, что и компьютер. "
        "Если Windows спросит про доступ к сети — нажми «Разрешить».</p>"
        "</body></html>"
    )


class _Handler(BaseHTTPRequestHandler):
    server_version = "TextRPGPhone/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, content_type="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send(200, MOBILE_HTML, "text/html; charset=utf-8")
            return
        if path == "/qr":
            self._send(200, _qr_page_html(), "text/html; charset=utf-8")
            return
        if path == "/qr.svg":
            svg = _qr_svg_bytes(phone_url())
            if svg is None:
                self._send(503, "Установи модуль qrcode: pip install qrcode")
            else:
                self._send(200, svg, "image/svg+xml; charset=utf-8")
            return
        if path == "/favicon.ico":
            self._send(204, b"")
            return
        if path == "/api/new":
            client_id = (qs.get("client", [""])[0] or "anon")[:100]
            sess, err = _new_session(client_id)
            if err:
                self._send(409, err)
                return
            sess.last_seen = time.monotonic()
            data = sess.snapshot(-1, -1)
            data["token"] = sess.token
            self._send(200, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")
            return
        if path == "/api/poll":
            token = qs.get("token", [""])[0]
            sess = _sessions.get(token)
            if sess is None:
                self._send(404, "Сессия не найдена. Обнови страницу.")
                return
            try:
                since = int(qs.get("since", ["0"])[0])
                clear = int(qs.get("clear", ["-1"])[0])
            except (TypeError, ValueError):
                self._send(400, "Плохие параметры")
                return
            sess.last_seen = time.monotonic()
            data = sess.snapshot(since, clear)
            self._send(200, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")
            return
        self._send(404, "Не найдено")

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/input":
            self._send(404, "Не найдено")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 20000:
            self._send(413, "Слишком большой запрос")
            return
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, "Плохой JSON")
            return
        token = data.get("token")
        text = data.get("text", "")
        sess = _sessions.get(token)
        if sess is None:
            self._send(404, "Сессия не найдена. Обнови страницу.")
            return
        if not isinstance(text, str):
            self._send(400, "Текст должен быть строкой")
            return
        sess.last_seen = time.monotonic()
        sess.submit(text[:1000])
        self._send(200, '{"ok":true}', "application/json; charset=utf-8")


# ---------------------------------------------------------------------------
# Запуск сессий
# ---------------------------------------------------------------------------

def _run_game(sess: GameSession):
    global _active
    _local.session = sess
    try:
        if _game_main is None:
            sess.write("\n❌ Игра не передала функцию запуска (main).\n")
            return
        _game_main()
    except SystemExit:
        pass
    except BaseException:
        sess.write("\n❌ Ошибка игры:\n" + traceback.format_exc())
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        _local.session = None
        with sess.lock:
            sess.closed = True
        sess.write("\n\n=== Игра завершена. Обнови страницу, чтобы начать заново. ===\n")
        with _lock:
            if _active is sess:
                _active = None


def _new_session(client_id: str):
    global _active
    with _lock:
        old = _by_client.get(client_id)
        if old is not None and not old.is_closed():
            return old, None
        if _active is not None and not _active.is_closed():
            return None, (
                "На другом устройстве уже запущена игра.\\n\\n"
                "Закрой ту вкладку (или заверши игру там) и обнови эту страницу.\\n"
                "Если телефон был закрыт давно, перезапусти игру на компьютере."
            )

        # старые закрытые сессии не храним вечно
        for tok, s in list(_sessions.items()):
            if s.is_closed() and s.client_id != client_id:
                _sessions.pop(tok, None)

        sess = GameSession(client_id)
        _by_client[client_id] = sess
        _sessions[sess.token] = sess
        _active = sess
        t = threading.Thread(target=_run_game, args=(sess,), daemon=True, name="phone-game")
        sess.thread = t
        t.start()
        return sess, None


def start_server(game_main) -> int:
    """Запускает HTTP-сервер (один раз) и возвращает порт."""
    global _server, _server_thread, _game_main, _port
    _game_main = game_main
    with _lock:
        if _server is not None:
            return _port
        last_err = None
        httpd = None
        port = 0
        for p in DEFAULT_PORTS:
            try:
                httpd = ThreadingHTTPServer(("0.0.0.0", p), _Handler)
                port = p
                break
            except OSError as e:
                last_err = e
                httpd = None
        if httpd is None:
            raise RuntimeError(f"Не удалось занять порт: {last_err}")
        httpd.daemon_threads = True
        _server = httpd
        _port = port
        t = threading.Thread(target=httpd.serve_forever, name="phone-http", daemon=True)
        _server_thread = t
        t.start()
        return port


def phone_menu(game_main):
    """Пункт меню «Играть на телефоне»: показывает QR и адрес."""
    sess = current_session()
    if sess is not None:
        sess.write("\n📱 QR-код и адрес показаны на экране компьютера.\n")
        return

    try:
        port = start_server(game_main)
    except Exception as e:
        print(f"❌ Не удалось запустить сервер: {e}")
        return

    url = phone_url()
    print("\n" + "=" * 62)
    print("📱 ИГРА НА ТЕЛЕФОНЕ")
    print("=" * 62)
    print("1. Подключи телефон к той же Wi-Fi сети, что и компьютер.")
    print("2. Если Windows спросит про доступ к сети — нажми «Разрешить».")
    print("3. Наведи камеру телефона на QR-код ниже.")
    print(f"\nАдрес для ручного ввода: {url}")
    print("⚠️  Сейв общий: не играй одновременно на ПК и телефоне.\n")

    lines = qr_ansi_lines(url)
    if lines:
        _enable_ansi()
        print("\n".join(lines))
        print()
    else:
        print("⚠️  Модуль qrcode не найден — QR в консоли не нарисовать.")
        print("    Установи: pip install qrcode")
        print("    Сервер уже работает, адрес можно ввести вручную.\n")

    try:
        answer = input("Открыть большой QR в браузере? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer == "y":
        try:
            webbrowser.open(f"http://127.0.0.1:{port}/qr")
        except Exception as e:
            print(f"❌ Не удалось открыть браузер: {e}")

    print("\nСервер работает, пока запущена игра. Нажми Enter, чтобы вернуться в меню.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
