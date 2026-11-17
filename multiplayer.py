# -*- coding: utf-8 -*-
"""LAN/QR-мультиплеер для текстовой RPG.

Режимы:
- team  — игроки сражаются вместе против волн врагов, могут передавать
          друг другу золото и ресурсы между волнами;
- pvp   — игроки сражаются друг против друга до последнего выжившего.

Подключение: телефон/ПК открывает ссылку из QR-кода, играет в браузере.
Bluetooth в этой версии не включён — для него нужен отдельный транспорт
и сопряжение устройств; LAN/QR работает без установки чего-либо на телефон.
"""

from __future__ import annotations

import io
import json
import os
import random
import secrets
import socket
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    import qrcode
    import qrcode.image.svg
except Exception:  # qrcode не обязателен: сервер и без него работает
    qrcode = None

PORT_RANGE = range(8030, 8060)
MIN_PLAYERS = 2
MAX_PLAYERS = 4
MAX_WAVES = 4
RESOURCE_NAMES = ("Трава", "Руда", "Кожа", "Кристалл")

CLASSES = {
    "Воин": {
        "hp": 150, "attack": 15, "defense": 10, "mana": 0,
        "ability": "Мощный удар", "ability_desc": "1.7x урон, перезарядка 2",
        "mana_cost": 0, "cooldown": 2, "needs_target": True,
    },
    "Маг": {
        "hp": 100, "attack": 10, "defense": 3, "mana": 50,
        "ability": "Огненный шар", "ability_desc": "1.9x урон, 15 маны",
        "mana_cost": 15, "cooldown": 0, "needs_target": True,
    },
    "Разбойник": {
        "hp": 80, "attack": 14, "defense": 6, "mana": 0,
        "ability": "Удар в спину", "ability_desc": "1.5x, 30% крит x2.5",
        "mana_cost": 0, "cooldown": 2, "needs_target": True,
    },
    "Танк": {
        "hp": 250, "attack": 6, "defense": 20, "mana": 0,
        "ability": "Глухая оборона", "ability_desc": "-70% урона до конца раунда",
        "mana_cost": 0, "cooldown": 2, "needs_target": False,
    },
    "Паладин": {
        "hp": 180, "attack": 10, "defense": 12, "mana": 0,
        "ability": "Святое лечение", "ability_desc": "+30 HP",
        "mana_cost": 0, "cooldown": 2, "needs_target": False,
    },
    "Некромант": {
        "hp": 90, "attack": 12, "defense": 4, "mana": 60,
        "ability": "Похищение жизни", "ability_desc": "1.3x, лечит 50% урона",
        "mana_cost": 15, "cooldown": 0, "needs_target": True,
    },
    "Берсерк": {
        "hp": 120, "attack": 20, "defense": 2, "mana": 0,
        "ability": "Кровавая ярость", "ability_desc": "2x урон, -10 HP",
        "mana_cost": 0, "cooldown": 2, "needs_target": True,
    },
    "Ассасин": {
        "hp": 70, "attack": 18, "defense": 5, "mana": 0,
        "ability": "Удар милосердия", "ability_desc": "20% казнь цели с HP < 35%",
        "mana_cost": 0, "cooldown": 3, "needs_target": True,
    },
    "Повелитель Времени": {
        "hp": 110, "attack": 12, "defense": 5, "mana": 80,
        "ability": "Откат времени", "ability_desc": "+20 HP и уклонение от атаки",
        "mana_cost": 20, "cooldown": 3, "needs_target": False,
    },
}

WAVES = [
    {"name": "🌲 Лесная засада", "enemies": [("Гоблин", 70, 9, 2), ("Гоблин", 70, 9, 2)],
     "gold": 40, "res": ("Трава", 2)},
    {"name": "🕷️ Пещера", "enemies": [("Скелет-воин", 100, 13, 4), ("Скелет-лучник", 80, 15, 2)],
     "gold": 60, "res": ("Руда", 2)},
    {"name": "⛰️ Логово огра", "enemies": [("Огр", 260, 20, 7), ("Гоблин-шаман", 110, 14, 3)],
     "gold": 90, "res": ("Кожа", 2),
     "boss": {"kind": "ogre", "every": 3, "enrage": 0.35,
              "desc": "БОСС. Каждые 3 раунда — сокрушающий удар. Ярость ниже 35% HP."}},
    {"name": "🐉 Дракон", "enemies": [("Дракон", 360, 24, 8)],
     "gold": 150, "res": ("Кристалл", 1),
     "boss": {"kind": "dragon", "every": 3, "enrage": 0.4,
              "desc": "БОСС. Каждые 3 раунда — дыхание пламенем по всем. Ярость ниже 40% HP."}},
]

DIFFICULTY = {
    "easy": {"label": "Лёгкая", "hp": 0.8, "atk": 0.8, "def": 0.85},
    "normal": {"label": "Обычная", "hp": 1.0, "atk": 1.0, "def": 1.0},
    "hard": {"label": "Сложная", "hp": 1.25, "atk": 1.2, "def": 1.15},
}
DEFAULT_SETTINGS = {
    "difficulty": "normal",
    "max_waves": MAX_WAVES,
    "turn_timer": 30,
    "start_gold": 50,
    "password": "",
}
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PASSWORD_MAX_FAILS = 5
PASSWORD_LOCK_SECONDS = 60
PASSWORD_WINDOW_SECONDS = 300

_lock = threading.RLock()
_state = None
_server = None
_port = 0
_join_url = ""
_tick_thread = None
_stop_event = threading.Event()


class MPPlayer:
    def __init__(self, pid, client_id, name, cls, gold=50):
        self.id = pid
        self.client_id = client_id
        self.token = secrets.token_urlsafe(24)
        self.resume_code = ""
        self.name = name
        self.cls = cls
        self.is_host = False
        self.ready = False
        self.chat_muted = False
        self.chat_slow = 0
        self.last_chat = 0.0
        self.last_seen = time.monotonic()
        self.action = None
        self.target = None
        self.guard = False
        self.dodge = False
        self.ability_cd = 0
        self.alive = True
        self.hp = self.max_hp = 1
        self.mana = self.max_mana = 0
        self.potions = 2
        self.gold = gold
        self.resources = {}
        self.reset_stats(gold)

    def reset_stats(self, gold=50):
        cfg = CLASSES[self.cls]
        self.max_hp = cfg["hp"]
        self.hp = self.max_hp
        self.attack = cfg["attack"]
        self.defense = cfg["defense"]
        self.max_mana = cfg["mana"]
        self.mana = self.max_mana
        self.potions = 2
        self.gold = gold
        self.resources = {"Трава": 2, "Руда": 1, "Кожа": 1}
        self.alive = True
        self.action = None
        self.target = None
        self.guard = False
        self.dodge = False
        self.ability_cd = 0


class MPEnemy:
    def __init__(self, eid, name, hp, attack, defense, boss=None):
        self.id = eid
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.attack = attack
        self.defense = defense
        self.alive = True
        self.is_boss = bool(boss)
        self.boss_kind = boss.get("kind") if boss else None
        self.special_every = int(boss.get("every", 3)) if boss else 0
        self.enrage_at = float(boss.get("enrage", 0)) if boss else 0
        self.boss_desc = boss.get("desc", "") if boss else ""
        self.enraged = False


class MPState:
    def __init__(self, mode):
        self.mode = mode
        self.phase = "lobby"
        self.players = {}
        self.order = []
        self.enemies = []
        self.wave = 0
        self.turn = 0
        self.turn_started = time.monotonic()
        self.log = []
        self.winner = None
        self.host_id = None
        self.version = 0
        self.next_id = 1
        self.room_code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        self.settings = dict(DEFAULT_SETTINGS)
        self.bans = {}
        self.shutdown_message = ""
        self.game_no = 0
        self.pw_fails = {}


def _mode_label(mode):
    return "🤝 Команда" if mode == "team" else "⚔️ PvP"


def _ordered_locked(st):
    return [st.players[pid] for pid in st.order if pid in st.players]


def _add_log_locked(st, text):
    st.log.append(str(text))
    if len(st.log) > 150:
        del st.log[:-150]
    st.version += 1


def _clean_name(name):
    name = "".join(ch for ch in str(name or "") if ch.isprintable())
    name = " ".join(name.split())[:16]
    return name or "Игрок"


def _new_resume_code(st):
    used = {q.resume_code for q in st.players.values() if q.resume_code}
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if code not in used:
            return code


def _public_settings(st):
    data = dict(st.settings)
    data.pop("password", None)
    data["has_password"] = bool(st.settings.get("password"))
    return data


def _public_player(st, p):
    return {
        "id": p.id,
        "name": p.name,
        "class": p.cls,
        "hp": p.hp,
        "max_hp": p.max_hp,
        "mana": p.mana,
        "max_mana": p.max_mana,
        "attack": p.attack,
        "defense": p.defense,
        "alive": p.alive,
        "acted": p.action is not None,
        "is_host": p.id == st.host_id,
        "ready": p.ready,
        "chat_muted": p.chat_muted,
        "chat_slow": p.chat_slow,
        "guard": p.guard,
        "potions": p.potions,
        "gold": p.gold,
        "resources": dict(p.resources),
    }


def _snapshot_locked(st, p):
    me = _public_player(st, p)
    cfg = CLASSES[p.cls]
    me.update({
        "ability": cfg["ability"],
        "ability_desc": cfg["ability_desc"],
        "ability_mana": cfg["mana_cost"],
        "ability_cd": p.ability_cd,
        "ability_target": cfg["needs_target"],
        "resume_code": p.resume_code,
        "action": p.action,
        "target": p.target,
    })
    waiting = []
    if st.phase == "battle":
        waiting = [q.name for q in _ordered_locked(st) if q.alive and q.action is None]
    bans = []
    if p.id == st.host_id:
        bans = [{"client": cid, "name": name, "short": cid[:8]}
                for cid, name in st.bans.items()]
    return {
        "version": st.version,
        "mode": st.mode,
        "mode_label": _mode_label(st.mode),
        "phase": st.phase,
        "game_no": st.game_no,
        "wave": st.wave,
        "max_waves": st.settings["max_waves"],
        "turn": st.turn,
        "players": [_public_player(st, q) for q in _ordered_locked(st)],
        "enemies": [{
            "id": e.id, "name": e.name, "hp": e.hp, "max_hp": e.max_hp,
            "attack": e.attack, "defense": e.defense, "alive": e.alive,
            "is_boss": e.is_boss, "enraged": e.enraged, "boss_desc": e.boss_desc,
        } for e in st.enemies],
        "you": me,
        "host_id": st.host_id,
        "waiting_for": waiting,
        "can_start": st.phase == "lobby" and len(st.players) >= MIN_PLAYERS and p.id == st.host_id,
        "all_ready": (st.phase == "lobby" and len(st.players) >= MIN_PLAYERS
                      and all(q.ready for q in st.players.values())),
        "min_players": MIN_PLAYERS,
        "max_players": MAX_PLAYERS,
        "settings": _public_settings(st),
        "room_code": st.room_code,
        "join_url": _join_url,
        "bans": bans,
        "shutdown": st.shutdown_message,
        "log": list(st.log[-60:]),
        "winner": st.winner,
    }


def _password_blocked_locked(st, key):
    if not key:
        return None
    now = time.monotonic()
    fails = [t for t in st.pw_fails.get(key, []) if now - t < PASSWORD_WINDOW_SECONDS]
    if fails:
        st.pw_fails[key] = fails
    else:
        st.pw_fails.pop(key, None)
    if len(fails) < PASSWORD_MAX_FAILS:
        return None
    wait = PASSWORD_LOCK_SECONDS - (now - fails[-1])
    if wait > 0:
        return f"Слишком много попыток пароля. Попробуй через {int(wait) + 1} с."
    st.pw_fails.pop(key, None)
    return None


def _password_failed_locked(st, key):
    if not key:
        return 0
    now = time.monotonic()
    fails = [t for t in st.pw_fails.get(key, []) if now - t < PASSWORD_WINDOW_SECONDS]
    fails.append(now)
    st.pw_fails[key] = fails[-PASSWORD_MAX_FAILS:]
    return len(fails)


def _join_locked(st, client_id, name, cls, password="", ip=""):
    if not client_id:
        return None, "Не передан идентификатор клиента."
    if client_id in st.bans:
        return None, "Вы забанены хостом этой комнаты."
    for p in st.players.values():
        if p.client_id == client_id:
            p.last_seen = time.monotonic()
            return p, None
    if st.settings.get("password"):
        key = str(ip or client_id)
        blocked = _password_blocked_locked(st, key)
        if blocked:
            return None, blocked
        if str(password or "") != st.settings["password"]:
            count = _password_failed_locked(st, key)
            left = PASSWORD_MAX_FAILS - count
            if left <= 0:
                return None, (f"Слишком много попыток пароля. "
                              f"Попробуй через {PASSWORD_LOCK_SECONDS} с.")
            return None, f"Неверный пароль комнаты. Осталось попыток: {left}."
        st.pw_fails.pop(key, None)
    if st.phase != "lobby":
        return None, "Игра уже началась. Новые игроки могут зайти только в лобби."
    if len(st.players) >= MAX_PLAYERS:
        return None, f"Комната заполнена (максимум {MAX_PLAYERS} игрока)."
    if cls not in CLASSES:
        return None, "Неизвестный класс."
    name = _clean_name(name)
    names = {q.name.lower() for q in st.players.values()}
    if name.lower() in names:
        base = name[:12]
        i = 2
        while f"{base} {i}".lower() in names:
            i += 1
        name = f"{base} {i}"[:16]
    pid = f"p{st.next_id}"
    st.next_id += 1
    p = MPPlayer(pid, client_id, name, cls, gold=st.settings["start_gold"])
    p.resume_code = _new_resume_code(st)
    st.players[pid] = p
    st.order.append(pid)
    if st.host_id is None:
        st.host_id = pid
        p.is_host = True
    _add_log_locked(st, f"➕ {p.name} присоединился: {p.cls}.")
    return p, None


def _resume_locked(st, code, client_id):
    code = "".join(str(code or "").split()).upper()
    if not code:
        return None, "Введи код возврата."
    if client_id and client_id in st.bans:
        return None, "Вы забанены хостом этой комнаты."
    for p in st.players.values():
        if p.resume_code == code:
            if client_id:
                p.client_id = client_id
            p.token = secrets.token_urlsafe(24)
            p.last_seen = time.monotonic()
            _add_log_locked(st, f"🔑 {p.name} вернулся в игру по коду.")
            return p, None
    return None, "Код возврата не найден. Проверь раскладку и регистр."


def _player_by_token_locked(st, token):
    for p in st.players.values():
        if p.token == token:
            return p
    return None


def _valid_target_locked(st, p, target_id):
    if st.mode == "team":
        for e in st.enemies:
            if e.id == target_id and e.alive:
                return e
        return None
    q = st.players.get(target_id)
    if q is not None and q.alive and q.id != p.id:
        return q
    return None


def _spawn_wave_locked(st, wave_no):
    wave = WAVES[wave_no - 1]
    diff = DIFFICULTY.get(st.settings.get("difficulty"), DIFFICULTY["normal"])
    n = max(1, len(st.players))
    hp_scale = (1 + 0.6 * max(0, n - 2)) * diff["hp"]
    atk_scale = (1 + 0.25 * max(0, n - 2)) * diff["atk"]
    def_scale = (1 + 0.15 * max(0, n - 2)) * diff["def"]
    st.enemies = []
    for j, (name, hp, attack, defense) in enumerate(wave["enemies"]):
        boss = wave.get("boss") if j == 0 else None
        st.enemies.append(MPEnemy(
            f"e{wave_no}_{j}", name,
            max(1, int(hp * hp_scale)),
            max(1, int(attack * atk_scale)),
            max(0, int(defense * def_scale)),
            boss=boss,
        ))


def _reset_round_flags(st):
    for p in _ordered_locked(st):
        p.action = None
        p.target = None
        p.guard = False
        p.dodge = False


def _start_locked(st, p):
    if st.phase != "lobby":
        return "Игра уже идёт."
    if p.id != st.host_id:
        return "Начать игру может только хост."
    if len(st.players) < MIN_PLAYERS:
        return f"Нужно минимум {MIN_PLAYERS} игрока."
    for q in st.players.values():
        q.ready = False
    st.winner = None
    st.turn = 1
    st.game_no += 1
    st.turn_started = time.monotonic()
    _reset_round_flags(st)
    if st.mode == "team":
        st.wave = 1
        _spawn_wave_locked(st, 1)
        st.phase = "battle"
        _add_log_locked(st, f"⚔️ Командный бой начался! Волна 1: {WAVES[0]['name']}.")
    else:
        st.wave = 0
        st.enemies = []
        st.phase = "battle"
        _add_log_locked(st, "⚔️ PvP начался! Побеждает последний выживший.")
    return None


def _ready_locked(st, p, ready):
    if st.phase != "lobby":
        return "Отметить готовность можно только в лобби."
    ready = bool(ready)
    if p.ready == ready:
        return None
    p.ready = ready
    p.last_seen = time.monotonic()
    _add_log_locked(st, f"✅ {p.name} готов." if ready else f"⏳ {p.name} не готов.")
    if (ready and len(st.players) >= MIN_PLAYERS
            and all(q.ready for q in st.players.values())):
        _add_log_locked(st, "🚀 Все готовы — начинаем игру!")
        host = st.players.get(st.host_id)
        if host is not None:
            err = _start_locked(st, host)
            if err:
                _add_log_locked(st, f"⚠️ Не удалось начать: {err}")
    return None


def _damage(attacker, defender, mult=1.0, pvp=False):
    if pvp:
        raw = attacker.attack * 2.0 * mult + 10
        red = defender.defense * 0.6
    else:
        raw = attacker.attack * 1.8 * mult + 5
        red = defender.defense * 0.7
    return max(1, int(raw - red + random.randint(-2, 2)))


def _apply_damage_locked(st, target, dmg, is_player=True):
    if is_player:
        if target.dodge:
            target.dodge = False
            _add_log_locked(st, f"💨 {target.name} уклоняется от атаки!")
            return 0
        if target.guard:
            dmg = max(1, int(dmg * 0.3))
        target.hp = max(0, target.hp - dmg)
        _add_log_locked(st, f"💥 {target.name} получает {dmg} урона (HP {target.hp}/{target.max_hp}).")
        if target.hp <= 0 and target.alive:
            target.alive = False
            _add_log_locked(st, f"💀 {target.name} пал!")
    else:
        target.hp = max(0, target.hp - dmg)
        _add_log_locked(st, f"💥 {target.name} получает {dmg} урона (HP {target.hp}/{target.max_hp}).")
        if target.hp <= 0 and target.alive:
            target.alive = False
            _add_log_locked(st, f"☠️ {target.name} повержен!")
    return dmg


def _use_ability_cost_locked(st, p):
    cfg = CLASSES[p.cls]
    p.mana = max(0, p.mana - cfg["mana_cost"])
    p.ability_cd = cfg["cooldown"] + 1


def _resolve_if_ready_locked(st):
    if st.phase != "battle":
        return
    alive = [p for p in _ordered_locked(st) if p.alive]
    if not alive:
        return
    if any(p.action is None for p in alive):
        return
    _resolve_round_locked(st)


def _resolve_round_locked(st):
    actors = [p for p in _ordered_locked(st) if p.alive and p.action]
    if st.mode == "pvp":
        random.shuffle(actors)
    pvp = st.mode == "pvp"

    # Сначала защита, зелья и лечебные способности.
    for p in actors:
        if p.action == "potion":
            p.potions -= 1
            before = p.hp
            p.hp = min(p.max_hp, p.hp + 30)
            _add_log_locked(st, f"🧪 {p.name} выпил зелье: +{p.hp - before} HP.")
        elif p.action == "guard":
            p.guard = True
            _add_log_locked(st, f"🛡️ {p.name} встаёт в защиту.")
        elif p.action == "skip":
            _add_log_locked(st, f"⏭️ {p.name} пропускает ход.")
        elif p.action == "ability":
            if p.cls == "Танк":
                p.guard = True
                _use_ability_cost_locked(st, p)
                _add_log_locked(st, f"🛡️ {p.name} использует «Глухую оборону».")
            elif p.cls == "Паладин":
                before = p.hp
                p.hp = min(p.max_hp, p.hp + 30)
                _use_ability_cost_locked(st, p)
                _add_log_locked(st, f"✨ {p.name} лечится: +{p.hp - before} HP.")
            elif p.cls == "Повелитель Времени":
                before = p.hp
                p.hp = min(p.max_hp, p.hp + 20)
                p.dodge = True
                _use_ability_cost_locked(st, p)
                _add_log_locked(st, f"⏳ {p.name} откатывает время: +{p.hp - before} HP и уклонение.")

    # Затем атаки и урон способностями.
    for p in actors:
        if not p.alive:
            continue
        if st.mode == "team" and not any(e.alive for e in st.enemies):
            break
        if p.action not in ("attack", "ability"):
            continue
        if p.action == "ability" and p.cls in ("Танк", "Паладин", "Повелитель Времени"):
            continue
        if p.action == "attack":
            target = _valid_target_locked(st, p, p.target)
            if target is None and st.mode == "team":
                alive_enemies = [e for e in st.enemies if e.alive]
                target = random.choice(alive_enemies) if alive_enemies else None
            if target is None:
                _add_log_locked(st, f"⚠️ {p.name} атакует, но цель уже мертва.")
                continue
            dmg = _damage(p, target, 1.0, pvp)
            _apply_damage_locked(st, target, dmg, is_player=pvp)
            continue

        # Способность с уроном.
        target = _valid_target_locked(st, p, p.target)
        if target is None and st.mode == "team":
            alive_enemies = [e for e in st.enemies if e.alive]
            target = random.choice(alive_enemies) if alive_enemies else None
        if target is None:
            _add_log_locked(st, f"⚠️ {p.name} применяет способность, но цель уже мертва.")
            _use_ability_cost_locked(st, p)
            continue

        cfg = CLASSES[p.cls]
        _use_ability_cost_locked(st, p)
        _add_log_locked(st, f"✨ {p.name} использует «{cfg['ability']}».")
        mult = 1.0
        special = None
        if p.cls == "Воин":
            mult = 1.7
        elif p.cls == "Маг":
            mult = 1.9
        elif p.cls == "Разбойник":
            mult = 1.5
            if random.random() < 0.3:
                mult = 2.5
                _add_log_locked(st, "🗡️ КРИТ!")
        elif p.cls == "Некромант":
            mult = 1.3
        elif p.cls == "Берсерк":
            mult = 2.0
            special = "berserk"
        elif p.cls == "Ассасин":
            if target.hp / max(1, target.max_hp) <= 0.35 and random.random() < 0.2:
                special = "execute"
            else:
                mult = 1.2

        if special == "execute":
            _apply_damage_locked(st, target, target.hp, is_player=pvp)
        else:
            dmg = _damage(p, target, mult, pvp)
            dmg = _apply_damage_locked(st, target, dmg, is_player=pvp)
            if p.cls == "Некромант":
                before = p.hp
                p.hp = min(p.max_hp, p.hp + max(1, dmg // 2))
                _add_log_locked(st, f"🩸 {p.name} похищает {p.hp - before} HP.")
            if special == "berserk":
                p.hp = max(0, p.hp - 10)
                _add_log_locked(st, f"🩸 Ярость берсерка: {p.name} теряет 10 HP.")
                if p.hp <= 0 and p.alive:
                    p.alive = False
                    _add_log_locked(st, f"💀 {p.name} пал от собственной ярости!")

    if st.mode == "team":
        if not any(e.alive for e in st.enemies):
            _wave_cleared_locked(st)
            return
        if not any(p.alive for p in _ordered_locked(st)):
            _game_over_locked(st, "defeat")
            return
        _enemy_phase_locked(st)
        if not any(p.alive for p in _ordered_locked(st)):
            _game_over_locked(st, "defeat")
            return
        if not any(e.alive for e in st.enemies):
            _wave_cleared_locked(st)
            return
    else:
        alive = [p for p in _ordered_locked(st) if p.alive]
        if len(alive) <= 1:
            _game_over_locked(st, alive[0].name if alive else "Ничья")
            return

    _next_round_locked(st)


def _enemy_hit_player_locked(st, p, dmg, source, guard_factor=0.3):
    if p.dodge:
        p.dodge = False
        _add_log_locked(st, f"💨 {p.name} уклоняется от атаки: {source}!")
        return 0
    if p.guard:
        dmg = max(1, int(dmg * guard_factor))
    p.hp = max(0, p.hp - dmg)
    _add_log_locked(st, f"👹 {source} наносит {p.name} {dmg} урона (HP {p.hp}/{p.max_hp}).")
    if p.hp <= 0 and p.alive:
        p.alive = False
        _add_log_locked(st, f"💀 {p.name} пал!")
    return dmg


def _enemy_phase_locked(st):
    for e in st.enemies:
        if not e.alive:
            continue
        targets = [p for p in _ordered_locked(st) if p.alive]
        if not targets:
            return
        if e.is_boss and e.enrage_at and not e.enraged and e.hp / max(1, e.max_hp) <= e.enrage_at:
            e.enraged = True
            e.attack = max(1, int(e.attack * 1.25))
            _add_log_locked(st, f"😡 {e.name} в ярости! Атака выросла.")
        if e.is_boss and e.special_every and st.turn % e.special_every == 0:
            if e.boss_kind == "dragon":
                _add_log_locked(st, f"🔥 {e.name} дышит пламенем!")
                for p in targets:
                    if not p.alive:
                        continue
                    dmg = max(1, int(e.attack * 0.8 + random.randint(-2, 2) - p.defense * 0.5))
                    _enemy_hit_player_locked(st, p, dmg, f"🔥 Пламя {e.name}", guard_factor=0.3)
                if not any(p.alive for p in _ordered_locked(st)):
                    return
                continue
            if e.boss_kind == "ogre":
                p = random.choice(targets)
                _add_log_locked(st, f"💢 {e.name} наносит сокрушающий удар!")
                dmg = max(1, int(e.attack * 1.5 + random.randint(-2, 2) - p.defense * 0.3))
                _enemy_hit_player_locked(st, p, dmg, "💢 Сокрушающий удар", guard_factor=0.5)
                continue
        p = random.choice(targets)
        dmg = max(1, int(e.attack + random.randint(-2, 2) - p.defense * 0.8))
        _enemy_hit_player_locked(st, p, dmg, e.name, guard_factor=0.3)


def _wave_cleared_locked(st):
    wave = WAVES[st.wave - 1]
    for p in _ordered_locked(st):
        if not p.alive:
            p.alive = True
            p.hp = max(1, p.max_hp // 2)
            _add_log_locked(st, f"🕊️ {p.name} возвращается в строй с 50% HP.")
        p.hp = min(p.max_hp, p.hp + 20)
        p.mana = min(p.max_mana, p.mana + 20)
        p.potions = min(5, p.potions + 1)
        p.gold += wave["gold"]
        res, amt = wave["res"]
        p.resources[res] = p.resources.get(res, 0) + amt
        p.action = None
        p.target = None
        p.guard = False
        p.dodge = False
    st.turn = 0
    if st.wave >= st.settings["max_waves"]:
        st.phase = "game_over"
        st.winner = "team"
        _add_log_locked(st, f"🏆 Волна {st.wave} пройдена! КОМАНДА ПОБЕДИЛА!")
    else:
        st.phase = "wave_clear"
        _add_log_locked(st, f"🏆 Волна {st.wave} пройдена! Передышка: можно передать ресурсы.")
    st.version += 1


def _next_round_locked(st):
    st.turn += 1
    st.turn_started = time.monotonic()
    for p in _ordered_locked(st):
        p.action = None
        p.target = None
        p.guard = False
        p.dodge = False
        if p.ability_cd > 0:
            p.ability_cd -= 1
        if p.max_mana > 0:
            p.mana = min(p.max_mana, p.mana + 5)
    st.version += 1


def _game_over_locked(st, winner):
    st.phase = "game_over"
    st.winner = winner
    if winner == "defeat":
        _add_log_locked(st, "💀 Команда пала. Попробуйте ещё раз!")
    elif winner == "team":
        _add_log_locked(st, "🏆 Команда победила!")
    elif winner == "Ничья":
        _add_log_locked(st, "🤝 Ничья!")
    else:
        _add_log_locked(st, f"🏆 Победитель: {winner}!")
    for p in _ordered_locked(st):
        p.action = None
        p.target = None
        p.guard = False
        p.dodge = False
    st.version += 1


def _next_wave_locked(st, p):
    if st.phase != "wave_clear":
        return "Сейчас нельзя начать следующую волну."
    if p.id != st.host_id:
        return "Следующую волну начинает только хост."
    if st.wave >= st.settings["max_waves"]:
        return "Это была последняя волна."
    st.wave += 1
    st.turn = 1
    st.turn_started = time.monotonic()
    _spawn_wave_locked(st, st.wave)
    st.phase = "battle"
    _reset_round_flags(st)
    _add_log_locked(st, f"⚔️ Волна {st.wave}: {WAVES[st.wave - 1]['name']}!")
    return None


def _transfer_locked(st, p, to_id, kind, resource, amount):
    if st.mode != "team":
        return "В PvP передача ресурсов запрещена."
    if st.phase not in ("lobby", "wave_clear"):
        return "Передавать ресурсы можно только в лобби или между волнами."
    q = st.players.get(to_id)
    if q is None or q.id == p.id:
        return "Выбери другого игрока."
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return "Неверное количество."
    if amount <= 0:
        return "Количество должно быть больше нуля."
    if kind == "gold":
        if p.gold < amount:
            return "Не хватает золота."
        p.gold -= amount
        q.gold += amount
        _add_log_locked(st, f"🎁 {p.name} передал {q.name} {amount} золота.")
    else:
        if resource not in RESOURCE_NAMES:
            return "Неизвестный ресурс."
        if p.resources.get(resource, 0) < amount:
            return f"Не хватает ресурса «{resource}»."
        p.resources[resource] = p.resources.get(resource, 0) - amount
        if p.resources[resource] <= 0:
            p.resources.pop(resource, None)
        q.resources[resource] = q.resources.get(resource, 0) + amount
        _add_log_locked(st, f"🎁 {p.name} передал {q.name}: {resource} x{amount}.")
    st.version += 1
    return None


def _chat_locked(st, p, text):
    text = " ".join(str(text or "").split())[:200]
    if not text:
        return "Пустое сообщение."
    if p.chat_muted:
        return "Хост запретил тебе писать в чат."
    now = time.monotonic()
    if p.chat_slow > 0:
        wait = p.chat_slow - (now - p.last_chat)
        if wait > 0:
            return f"Медленный режим: подожди ещё {int(wait + 0.99)} с."
    p.last_chat = now
    _add_log_locked(st, f"💬 {p.name}: {text}")
    return None


def _rename_locked(st, p, name):
    new_name = _clean_name(name)
    if new_name == p.name:
        return "Это твоё текущее имя."
    names = {q.name.lower() for q in st.players.values() if q.id != p.id}
    if new_name.lower() in names:
        base = new_name[:12]
        i = 2
        while f"{base} {i}".lower() in names:
            i += 1
        new_name = f"{base} {i}"[:16]
    old_name = p.name
    p.name = new_name
    p.last_seen = time.monotonic()
    _add_log_locked(st, f"✏️ {old_name} теперь {new_name}.")
    st.version += 1
    return None


def _restart_locked(st, p):
    if st.phase != "game_over":
        return "Перезапуск доступен только после конца игры."
    if p.id != st.host_id:
        return "Перезапустить игру может только хост."
    for q in _ordered_locked(st):
        q.reset_stats(gold=st.settings["start_gold"])
        q.ready = False
    st.phase = "lobby"
    st.wave = 0
    st.turn = 0
    st.enemies = []
    st.winner = None
    _add_log_locked(st, "🔄 Лобби перезапущено. Хост может начать новую игру.")
    return None


def _settings_locked(st, p, data):
    if p.id != st.host_id:
        return "Настройки меняет только хост."
    if st.phase != "lobby":
        return "Настройки можно менять только в лобби."
    difficulty = str(data.get("difficulty", st.settings["difficulty"]))
    if difficulty not in DIFFICULTY:
        return "Неизвестная сложность."
    try:
        max_waves = int(data.get("max_waves", st.settings["max_waves"]))
        turn_timer = int(data.get("turn_timer", st.settings["turn_timer"]))
        start_gold = int(data.get("start_gold", st.settings["start_gold"]))
    except (TypeError, ValueError):
        return "Неверные числовые настройки."
    if not (2 <= max_waves <= len(WAVES)):
        return f"Волн может быть от 2 до {len(WAVES)}."
    if not (10 <= turn_timer <= 300):
        return "Таймер хода: от 10 до 300 секунд."
    if not (0 <= start_gold <= 5000):
        return "Стартовое золото: от 0 до 5000."

    password = data.get("password", None)
    if password is not None:
        password = str(password)[:24]
        if password:
            st.settings["password"] = password
    if data.get("clear_password"):
        st.settings["password"] = ""

    old_gold = st.settings["start_gold"]
    st.settings.update({
        "difficulty": difficulty,
        "max_waves": max_waves,
        "turn_timer": turn_timer,
        "start_gold": start_gold,
    })
    if start_gold != old_gold:
        for q in st.players.values():
            q.gold = start_gold
    _add_log_locked(st, "⚙️ Хост обновил настройки комнаты.")
    st.version += 1
    return None


def _remove_player_locked(st, target):
    st.players.pop(target.id, None)
    if target.id in st.order:
        st.order.remove(target.id)
    if st.phase != "battle":
        st.version += 1
        return
    alive = [q for q in _ordered_locked(st) if q.alive]
    if st.mode == "pvp":
        if len(alive) <= 1:
            _game_over_locked(st, alive[0].name if alive else "Ничья")
            return
    elif not alive:
        _game_over_locked(st, "defeat")
        return
    _resolve_if_ready_locked(st)
    st.version += 1


def _admin_locked(st, actor, action, target_id=None, value=None):
    if actor.id != st.host_id:
        return "Админ-панель доступна только хосту."
    if action == "unban":
        cid = str(value or "")
        if cid and cid in st.bans:
            name = st.bans.pop(cid)
            _add_log_locked(st, f"✅ {name} разбанен хостом.")
        else:
            return "Такого бана нет."
        return None
    target = st.players.get(str(target_id or ""))
    if target is None:
        return "Игрок не найден."
    if target.id == actor.id:
        return "Нельзя применить это к себе."
    if action == "kick":
        _remove_player_locked(st, target)
        _add_log_locked(st, f"👢 Хост исключил {target.name}.")
    elif action == "ban":
        st.bans[target.client_id] = target.name
        _remove_player_locked(st, target)
        _add_log_locked(st, f"🚫 Хост забанил {target.name}.")
    elif action == "transfer":
        actor.is_host = False
        target.is_host = True
        st.host_id = target.id
        _add_log_locked(st, f"👑 Новый хост: {target.name}.")
        st.version += 1
    elif action == "mute":
        target.chat_muted = True
        _add_log_locked(st, f"🔇 Хост запретил {target.name} писать в чат.")
        st.version += 1
    elif action == "unmute":
        if not target.chat_muted:
            return "Игрок и так может писать в чат."
        target.chat_muted = False
        _add_log_locked(st, f"🔊 Хост снова разрешил {target.name} писать в чат.")
        st.version += 1
    elif action == "slow":
        try:
            secs = int(value or 0)
        except (TypeError, ValueError):
            return "Неверный интервал медленного режима."
        if secs not in (0, 5, 10, 30):
            return "Интервал: выкл, 5, 10 или 30 секунд."
        target.chat_slow = secs
        if secs:
            _add_log_locked(st, f"🐢 Хост ограничил чат {target.name}: не чаще 1 сообщения в {secs} с.")
        else:
            _add_log_locked(st, f"💬 Хост снял ограничение чата с {target.name}.")
        st.version += 1
    else:
        return "Неизвестное админ-действие."
    return None


def _tick_loop():
    while not _stop_event.wait(2.0):
        try:
            with _lock:
                st = _state
                if st is None:
                    continue
                now = time.monotonic()
                # Передача хоста, если хост отвалился.
                host = st.players.get(st.host_id) if st.host_id else None
                if host is not None and now - host.last_seen > 30:
                    alive_hosts = [q for q in _ordered_locked(st) if now - q.last_seen <= 30]
                    if alive_hosts:
                        host.is_host = False
                        new_host = alive_hosts[0]
                        st.host_id = new_host.id
                        new_host.is_host = True
                        _add_log_locked(st, f"👑 Новый хост: {new_host.name}.")
                if st.phase == "battle" and now - st.turn_started > st.settings["turn_timer"]:
                    changed = False
                    for q in _ordered_locked(st):
                        if q.alive and q.action is None:
                            q.action = "skip"
                            q.target = None
                            changed = True
                            _add_log_locked(st, f"⏳ Время на ход вышло — {q.name} пропускает.")
                    if changed:
                        _resolve_if_ready_locked(st)
        except Exception:
            traceback.print_exc()


def _primary_ip():
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


def _qr_matrix(data):
    if qrcode is None:
        return None
    try:
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(data)
        qr.make(fit=True)
        return qr.get_matrix()
    except Exception:
        return None


def qr_ansi_lines(data):
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
            fg = "30" if top else "97"
            bg = "40" if bottom else "107"
            row.append(f"\x1b[{fg};{bg}m▀")
        row.append("\x1b[0m")
        lines.append("".join(row))
    return lines


def _enable_ansi():
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


def _qr_svg_bytes(data):
    if qrcode is None:
        return None
    try:
        img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage,
                          border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue()
    except Exception:
        return None


def _qr_page_html():
    url = f"http://{_primary_ip()}:{_port}/"
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>QR — Мультиплеер</title><style>"
        "body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;"
        "background:#fff;color:#111;font-family:system-ui,Segoe UI,Arial,sans-serif;text-align:center}"
        "h1{font-size:24px;margin:14px 16px}img{width:min(78vmin,520px);height:auto;image-rendering:pixelated}"
        "code{font-size:17px;background:#f0f0f0;padding:8px 12px;border-radius:8px;display:inline-block;margin:8px;word-break:break-all}"
        "p{max-width:660px;margin:6px 18px;color:#444;font-size:15px;line-height:1.45}"
        "</style></head><body>"
        "<h1>📱 Наведи камеру телефона</h1>"
        "<img src='/qr.svg' alt='QR-код'>"
        f"<p>Адрес: <code>{url}</code></p>"
        "<p>Телефон должен быть в той же Wi-Fi сети, что и компьютер. "
        "Открой ссылку и присоединись к лобби.</p>"
        "</body></html>"
    )


MOBILE_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#111a22">
<title>Мультиплеер — Текстовая RPG</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b1016;color:#d8e2ea;font-family:ui-monospace,Consolas,"Courier New",monospace;min-height:100dvh}
header{display:flex;align-items:center;gap:10px;padding:9px 12px;background:#111a22;border-bottom:1px solid #22303c;position:sticky;top:0;z-index:5}
header .title{flex:1;font-weight:700;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#status{font-size:12px;white-space:nowrap}#status.ok{color:#4ade80}#status.bad{color:#f87171}
#view{padding:10px 12px 44px;max-width:1100px;margin:0 auto}
h1{font-size:20px;margin:8px 0}h2{font-size:15px;margin:14px 0 6px}
.muted{color:#8fa3b3;font-size:12px;line-height:1.45}
.card{background:#111a22;border:1px solid #22303c;border-radius:12px;padding:10px;margin:8px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bar{height:8px;background:#1d2a35;border-radius:6px;overflow:hidden;margin:6px 0}
.bar>i{display:block;height:100%;background:#4ade80}.bar.hp>i{background:#f87171}.bar.mp>i{background:#60a5fa}
button{font:inherit;border:0;border-radius:10px;background:#e2b13c;color:#17120a;padding:10px 14px;font-weight:700;cursor:pointer}
button:active{transform:translateY(1px)}button:disabled{opacity:.4;cursor:default;transform:none}
button.alt{background:#1d2a35;color:#d8e2ea}
input,select{font:inherit;background:#0b1016;color:#fff;border:1px solid #2c3e4c;border-radius:9px;padding:9px 10px;max-width:100%}
input[type=number]{width:90px}
.log{background:#0e151c;border:1px solid #1a2530;border-radius:10px;padding:9px;max-height:230px;overflow-y:auto;font-size:12px;line-height:1.4;white-space:pre-wrap}
.log div{padding:1px 0;word-break:break-word}
.tag{font-size:11px;padding:2px 6px;border-radius:999px;background:#1d2a35;color:#8fa3b3}
.tag.you{background:#e2b13c;color:#17120a}.tag.host{background:#a78bfa;color:#17120a}
.dead{opacity:.45}.enemy{border-color:#5b2b2b}
.err{color:#f87171;min-height:18px;font-size:13px}
.classbtn{display:block;width:100%;text-align:left;background:#111a22;color:#d8e2ea;border:1px solid #22303c;margin:4px 0;padding:9px 10px}
.classbtn.sel{border-color:#e2b13c;background:#1a2430}
.tag.boss{background:#7f1d1d;color:#fecaca;font-weight:700}.tag.enraged{background:#f97316;color:#17120a;font-weight:700}
.tag.admin{background:#a78bfa;color:#17120a}
.tag.ready{background:#166534;color:#bbf7d0;font-weight:700}.tag.notready{background:#1d2a35;color:#8fa3b3}
.tag.chatmuted{background:#7f1d1d;color:#fecaca}.tag.chatslow{background:#78350f;color:#fde68a}
.shutdown{background:#7f1d1d;border:1px solid #f87171;color:#fecaca;border-radius:10px;padding:10px 12px;margin:8px 0;font-weight:700;font-size:13px;line-height:1.4}
button.danger{background:#b91c1c;color:#fff}
button.namebtn{background:none;color:#d8e2ea;padding:0;font-weight:700;font-size:inherit;text-align:left;border-radius:6px}
button.namebtn:hover{color:#e2b13c}
.chipmute{outline:1px solid #f87171}
button.small{padding:6px 9px;font-size:12px;border-radius:8px}
details.card>summary{cursor:pointer;font-weight:700;font-size:14px;padding:2px 0}
code.code{background:#0b1016;border:1px solid #22303c;border-radius:8px;padding:5px 8px;font-size:12px;word-break:break-all}
.adminrow{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:6px 0;padding:6px 0;border-top:1px solid #1a2530}
.adminrow:first-of-type{border-top:0}
</style>
</head>
<body>
<header><span class="title">🌐 МУЛЬТИПЛЕЕР</span><span id="status" class="bad">●</span></header>
<main id="view"></main>
<script>
const CLASSES = __CLASSES_JSON__;
const MODE = __MODE_JSON__;
const MODE_LABEL = MODE === 'team' ? '🤝 Команда' : '⚔️ PvP';
const DIFF_LABEL = { easy: 'Лёгкая', normal: 'Обычная', hard: 'Сложная' };
let token = localStorage.getItem('mp_token') || '';
let client = localStorage.getItem('mp_client');
if (!client) {
  client = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('c' + Date.now() + Math.random().toString(16).slice(2));
  localStorage.setItem('mp_client', client);
}
let savedName = localStorage.getItem('mp_name') || '';
let savedClass = localStorage.getItem('mp_class') || '';
let current = null, lastVersion = -1, busy = false, polling = false, pollTimer = null;
let chatDraft = '', chatFocusWanted = false;
let renamingName = false, renameDraft = '', renameFocusWanted = false;
let localMuted = [], localMutedRoom = '';
const PROFILE_KEY = 'mp_profile_v1';
const LAST_ROOM_KEY = 'mp_last_room_v1';

function $(id) { return document.getElementById(id); }
function div(cls, text) { const d = document.createElement('div'); if (cls) d.className = cls; if (text !== undefined) d.textContent = text; return d; }
function h1(text) { const e = document.createElement('h1'); e.textContent = text; return e; }
function h2(text) { const e = document.createElement('h2'); e.textContent = text; return e; }
function btn(text, cls) { const b = document.createElement('button'); b.textContent = text; if (cls) b.className = cls; return b; }
function bar(cls, value, max) { const b = div('bar ' + cls); const i = document.createElement('i'); i.style.width = Math.max(0, Math.min(100, max ? value / max * 100 : 0)) + '%'; b.append(i); return b; }
function selectEl(options, value, id) {
  const s = document.createElement('select'); if (id) s.id = id;
  options.forEach(function (o) {
    const opt = new Option(o[0], o[1]);
    if (String(o[1]) === String(value)) opt.selected = true;
    s.append(opt);
  });
  return s;
}
function copyText(text, btnEl) {
  const done = function () {
    if (!btnEl) return;
    const old = btnEl.textContent; btnEl.textContent = '✅';
    setTimeout(function () { btnEl.textContent = old; }, 1200);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(function () { window.prompt('Скопируй:', text); });
  } else {
    window.prompt('Скопируй:', text);
  }
}
function setStatus(ok) { const s = $('status'); s.className = ok ? 'ok' : 'bad'; s.textContent = ok ? '● онлайн' : '● нет связи'; }
function showError(msg) { const e = $('err'); if (e) e.textContent = msg || ''; }
function logBox(lines) {
  const box = div('log');
  (lines || []).forEach(function (line) { const d = div('', line); box.append(d); });
  setTimeout(function () { box.scrollTop = box.scrollHeight; }, 20);
  return box;
}
function mutedStorageKey() { return 'mp_muted_' + ((current && current.room_code) || 'none'); }
function normalizeMuted(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  raw.forEach(function (item) {
    if (typeof item === 'string') out.push({ id: item, names: [] });
    else if (item && item.id) out.push({ id: String(item.id), names: Array.isArray(item.names) ? item.names.filter(Boolean) : [] });
  });
  return out;
}
function ensureMutedForRoom() {
  const room = current && current.room_code ? current.room_code : '';
  if (room === localMutedRoom) return;
  localMutedRoom = room;
  try { localMuted = normalizeMuted(JSON.parse(localStorage.getItem(mutedStorageKey()) || '[]')); } catch (e) { localMuted = []; }
}
function saveLocalMuted() { localStorage.setItem(mutedStorageKey(), JSON.stringify(localMuted)); }
function syncMutedNames() {
  if (!current || !current.players) return;
  let changed = false;
  localMuted.forEach(function (entry) {
    const p = current.players.filter(function (q) { return q.id === entry.id; })[0];
    if (p && entry.names.indexOf(p.name) < 0) { entry.names.push(p.name); changed = true; }
  });
  if (changed) saveLocalMuted();
}
function toggleLocalMute(id) {
  ensureMutedForRoom();
  const idx = localMuted.findIndex(function (entry) { return entry.id === id; });
  if (idx >= 0) {
    localMuted.splice(idx, 1);
  } else {
    const p = current.players.filter(function (q) { return q.id === id; })[0];
    localMuted.push({ id: id, names: p ? [p.name] : [] });
  }
  saveLocalMuted();
  render();
}
function isChatLineFromMuted(line) {
  if (!line.startsWith('💬 ')) return false;
  const body = line.slice(3);
  return localMuted.some(function (entry) {
    return entry.names.some(function (name) { return body.startsWith(name + ':'); });
  });
}
function loadProfile() {
  let p = null;
  try { p = JSON.parse(localStorage.getItem(PROFILE_KEY) || 'null'); } catch (e) { p = null; }
  p = p && typeof p === 'object' ? p : {};
  return {
    games: p.games || 0,
    wins: p.wins || 0,
    rooms: Array.isArray(p.rooms) ? p.rooms : [],
    classes: p.classes && typeof p.classes === 'object' ? p.classes : {},
    seen: Array.isArray(p.seen) ? p.seen : [],
    winSeen: Array.isArray(p.winSeen) ? p.winSeen : []
  };
}
function saveProfile(p) { localStorage.setItem(PROFILE_KEY, JSON.stringify(p)); }
function recordProfile() {
  if (!current || !current.you || !current.game_no) return;
  if (current.phase !== 'battle' && current.phase !== 'wave_clear' && current.phase !== 'game_over') return;
  const prof = loadProfile();
  const key = current.room_code + ':' + current.game_no;
  let changed = false;
  if (prof.seen.indexOf(key) < 0) {
    prof.seen.push(key);
    if (prof.seen.length > 200) prof.seen = prof.seen.slice(-200);
    prof.games += 1;
    if (prof.rooms.indexOf(current.room_code) < 0) prof.rooms.push(current.room_code);
    const cls = current.you['class'];
    prof.classes[cls] = (prof.classes[cls] || 0) + 1;
    changed = true;
  }
  if (current.phase === 'game_over' && current.winner && prof.winSeen.indexOf(key) < 0) {
    const won = current.mode === 'team' ? current.winner === 'team' : current.winner === current.you.name;
    if (won) prof.wins += 1;
    prof.winSeen.push(key);
    if (prof.winSeen.length > 200) prof.winSeen = prof.winSeen.slice(-200);
    changed = true;
  }
  if (changed) saveProfile(prof);
}
function favoriteClass(prof) {
  let best = '—', bestCount = 0;
  Object.keys(prof.classes).forEach(function (cls) {
    if (prof.classes[cls] > bestCount) { best = cls; bestCount = prof.classes[cls]; }
  });
  return best + (bestCount ? ' (' + bestCount + ')' : '');
}
async function saveRename() {
  if (busy) return;
  const name = renameDraft.trim();
  if (!name) { showError('Имя не может быть пустым.'); return; }
  busy = true; showError('');
  try {
    const d = await post('/api/rename', { token: token, name: name });
    current = d.state; lastVersion = d.state.version;
    renamingName = false; renameDraft = ''; render();
  } catch (e) {
    showError(e.message);
  } finally {
    busy = false;
  }
}
function saveLastRoom() {
  if (!current || !current.you || !current.room_code) return;
  const data = {
    code: current.room_code,
    mode: current.mode,
    mode_label: current.mode_label,
    name: current.you.name,
    cls: current.you['class'],
    resume: current.you.resume_code || '',
    has_password: !!(current.settings && current.settings.has_password),
    at: Date.now()
  };
  let prev = null;
  try { prev = JSON.parse(localStorage.getItem(LAST_ROOM_KEY) || 'null'); } catch (e) { prev = null; }
  const same = prev && prev.code === data.code && prev.mode === data.mode &&
    prev.name === data.name && prev.cls === data.cls && prev.resume === data.resume;
  if (!same || !prev.at || Date.now() - prev.at > 10 * 60 * 1000) {
    try { localStorage.setItem(LAST_ROOM_KEY, JSON.stringify(data)); } catch (e) {}
  }
}
function loadLastRoom() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(LAST_ROOM_KEY) || 'null'); } catch (e) { d = null; }
  if (!d || !d.code) return null;
  if (d.at && Date.now() - d.at > 7 * 24 * 3600 * 1000) return null;
  return d;
}
function forgetLastRoom() {
  localStorage.removeItem(LAST_ROOM_KEY);
  renderJoin();
}
function fmtWhen(ms) {
  const mins = Math.round((Date.now() - ms) / 60000);
  if (mins < 1) return 'только что';
  if (mins < 60) return mins + ' мин назад';
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return hrs + ' ч назад';
  return Math.round(hrs / 24) + ' дн назад';
}
async function returnToLastRoom(last) {
  if (busy) return;
  busy = true; showError('');
  const cls = CLASSES[last.cls] ? last.cls : 'Воин';
  let errMsg = '';
  try {
    if (last.resume) {
      try {
        const d = await post('/api/join', { client: client, resume: last.resume });
        savedName = d.state.you.name; localStorage.setItem('mp_name', savedName);
        saveSession(d);
        return;
      } catch (e) { errMsg = e.message; }
    }
    try {
      const d = await post('/api/join', { client: client, name: last.name || '', 'class': cls, password: '' });
      savedName = d.state.you.name; localStorage.setItem('mp_name', savedName);
      saveSession(d);
      return;
    } catch (e) { errMsg = e.message; }
    renderJoin(errMsg, { name: last.name || '', cls: cls, focus: /парол/i.test(errMsg) ? 'pass' : 'name' });
  } finally {
    busy = false;
  }
}
async function api(path, opts) {
  const r = await fetch(path, opts || {});
  let data = {};
  try { data = await r.json(); } catch (e) { data = { error: await r.text() }; }
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}
function post(path, body) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
}
function saveSession(d) {
  token = d.token; current = d.state; lastVersion = -1;
  localStorage.setItem('mp_token', token);
  render();
  startPolling();
}
function logout() {
  token = ''; localStorage.removeItem('mp_token'); current = null; lastVersion = -1;
  clearTimeout(pollTimer); renderJoin();
}
function playerCard(p, opts) {
  const c = div('card' + (p.alive ? '' : ' dead'));
  const top = div('row');
  if (p.id === current.you.id && renamingName) {
    const inp = document.createElement('input');
    inp.id = 'rename-input'; inp.maxLength = 16; inp.placeholder = 'Новое имя';
    inp.value = renameDraft; inp.style.flex = '1';
    inp.addEventListener('input', function () { renameDraft = inp.value; });
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); saveRename(); }
      else if (e.key === 'Escape') { renamingName = false; renameDraft = ''; render(); }
    });
    const ok = btn('Сохранить', 'alt'); ok.classList.add('small'); ok.onclick = saveRename;
    const cancel = btn('Отмена', 'alt'); cancel.classList.add('small');
    cancel.onclick = function () { renamingName = false; renameDraft = ''; render(); };
    top.append(inp, ok, cancel);
  } else if (p.id === current.you.id) {
    const nm = btn(p.name + ' ✏️', 'namebtn');
    nm.title = 'Нажми, чтобы изменить имя';
    nm.onclick = function () { renamingName = true; renameDraft = p.name; renameFocusWanted = true; render(); };
    top.append(nm);
  } else {
    const nm = div('', p.name); nm.style.fontWeight = '700'; top.append(nm);
  }
  if (p.id === current.you.id) { const t = div('tag you', 'вы'); top.append(t); }
  if (p.is_host) { const t = div('tag host', 'хост'); top.append(t); }
  if (current.phase === 'lobby') top.append(div('tag ' + (p.ready ? 'ready' : 'notready'), p.ready ? '✅ готов' : '⏳ не готов'));
  if (p.chat_muted) top.append(div('tag chatmuted', '🔇 мут'));
  if (p.chat_slow) top.append(div('tag chatslow', '🐢 ' + p.chat_slow + ' с'));
  top.append(div('tag', p['class']));
  c.append(top);
  c.append(div('muted', 'HP ' + p.hp + '/' + p.max_hp + '  ⚔️' + p.attack + '  🛡️' + p.defense));
  c.append(bar('hp', p.hp, p.max_hp));
  if (p.max_mana > 0) { c.append(div('muted', 'MP ' + p.mana + '/' + p.max_mana)); c.append(bar('mp', p.mana, p.max_mana)); }
  if (opts && opts.details) {
    c.append(div('muted', '🧪 Зелья: ' + p.potions + '  💰 ' + p.gold + ' золота'));
    if (p.resources && Object.keys(p.resources).length) {
      c.append(div('muted', 'Ресурсы: ' + Object.keys(p.resources).map(function (k) { return k + ' x' + p.resources[k]; }).join(', ')));
    }
  }
  if (!p.alive) c.append(div('muted', '💀 Выбыл'));
  else if (current.phase === 'battle') c.append(div('muted', p.acted ? '✅ Ход принят' : '⏳ Ждём ход'));
  return c;
}
function renderPlayers(container, details) {
  const g = div('grid');
  current.players.forEach(function (p) { g.append(playerCard(p, { details: details })); });
  container.append(g);
}
function renderLogInto(container) {
  ensureMutedForRoom();
  container.append(logBox(current.log.filter(function (line) { return !isChatLineFromMuted(line); })));
}
function renderChat(container) {
  const c = div('card');
  c.append(h2('💬 Чат'));
  const row = div('row');
  const inp = document.createElement('input'); inp.id = 'chat'; inp.maxLength = 200; inp.placeholder = 'Сообщение команде…'; inp.style.flex = '1';
  inp.value = chatDraft;
  inp.addEventListener('input', function () { chatDraft = inp.value; });
  const send = btn('Отправить', 'alt');
  if (current.you.chat_muted) {
    inp.disabled = true; send.disabled = true;
    inp.placeholder = 'Хост запретил тебе писать';
    c.append(div('err', '🔇 Хост запретил тебе писать в чат.'));
  } else if (current.you.chat_slow) {
    c.append(div('muted', '🐢 Медленный режим: не чаще 1 сообщения в ' + current.you.chat_slow + ' с.'));
  }
  send.onclick = async function () {
    const text = inp.value.trim(); if (!text || busy) return; busy = true;
    try {
      const d = await post('/api/chat', { token: token, text: text });
      chatDraft = ''; current = d.state; lastVersion = d.state.version; render();
    } catch (e) { showError(e.message); } finally { busy = false; }
  };
  inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') send.click(); });
  row.append(inp, send); c.append(row);
  ensureMutedForRoom();
  const others = current.players.filter(function (p) { return p.id !== current.you.id; });
  if (others.length) {
    const mrow = div('row');
    mrow.append(div('muted', 'Скрыть чат локально:'));
    others.forEach(function (p) {
      const active = localMuted.some(function (entry) { return entry.id === p.id; });
      const b = btn((active ? '🔊 ' : '🔇 ') + p.name, 'alt');
      b.classList.add('small');
      if (active) b.classList.add('chipmute');
      b.title = active ? 'Снова показывать сообщения' : 'Не показывать сообщения этого игрока у тебя';
      b.onclick = function () { toggleLocalMute(p.id); };
      mrow.append(b);
    });
    c.append(mrow);
  }
  container.append(c);
  if (chatFocusWanted) {
    inp.focus();
    const end = inp.value.length;
    inp.setSelectionRange(end, end);
  }
}

function resumeBar() {
  const c = div('card');
  const row = div('row');
  row.append(div('muted', 'Комната: ' + current.room_code));
  row.append(div('tag', '🔑 ' + current.you.resume_code));
  const cp = btn('Копировать код', 'alt'); cp.classList.add('small');
  cp.onclick = function () { copyText(current.you.resume_code, cp); };
  row.append(cp);
  c.append(row);
  c.append(div('muted', 'Сохрани код возврата — по нему можно вернуться, даже если вкладка закрылась.'));
  return c;
}

function renderProfileCard() {
  const p = loadProfile();
  const d = document.createElement('details'); d.className = 'card';
  const s = document.createElement('summary'); s.textContent = '👤 Мой профиль'; d.append(s);
  const rate = p.games ? Math.round(p.wins / p.games * 100) : 0;
  d.append(div('muted', 'Игр: ' + p.games + ' • Побед: ' + p.wins + ' (' + rate + '%)'));
  d.append(div('muted', 'Комнат: ' + p.rooms.length + ' • Любимый класс: ' + favoriteClass(p)));
  if (p.rooms.length) {
    const last = p.rooms.slice(-5).join(', ');
    d.append(div('muted', 'Последние комнаты: ' + last));
  }
  d.append(div('muted', 'Статистика хранится только в этом браузере.'));
  const reset = btn('Сбросить статистику', 'alt'); reset.classList.add('small');
  reset.onclick = function () {
    if (confirm('Сбросить статистику мультиплеера в этом браузере?')) {
      localStorage.removeItem(PROFILE_KEY);
      render();
    }
  };
  d.append(reset);
  return d;
}

async function adminAct(action, target, value) {
  if (busy) return;
  busy = true; showError('');
  try {
    const d = await post('/api/admin', { token: token, action: action, target: target || null, value: value || null });
    current = d.state; lastVersion = d.state.version; render();
  } catch (e) {
    showError(e.message);
  } finally {
    busy = false;
  }
}

function renderAdminPanel() {
  const d = document.createElement('details'); d.className = 'card';
  const s = document.createElement('summary'); s.textContent = '👑 Админ-панель'; d.append(s);
  const others = current.players.filter(function (p) { return p.id !== current.you.id; });
  if (!others.length) d.append(div('muted', 'В комнате пока никого нет.'));
  others.forEach(function (p) {
    const row = div('adminrow');
    const nm = div('', p.name + ' · ' + p['class']); nm.style.flex = '1';
    if (p.chat_muted) nm.append(div('tag chatmuted', '🔇 мут'));
    if (p.chat_slow) nm.append(div('tag chatslow', '🐢 ' + p.chat_slow + ' с'));
    const kick = btn('Кикнуть', 'alt'); kick.classList.add('small');
    kick.onclick = function () { if (confirm('Исключить ' + p.name + '?')) adminAct('kick', p.id); };
    const ban = btn('Забанить', 'danger'); ban.classList.add('small');
    ban.onclick = function () { if (confirm('Забанить ' + p.name + '? Он не сможет зайти в эту комнату.')) adminAct('ban', p.id); };
    const host = btn('Сделать хостом', 'alt'); host.classList.add('small');
    host.onclick = function () { if (confirm('Передать права хоста игроку ' + p.name + '?')) adminAct('transfer', p.id); };
    const mute = btn(p.chat_muted ? 'Размутить' : 'Мут', 'alt'); mute.classList.add('small');
    mute.onclick = function () { adminAct(p.chat_muted ? 'unmute' : 'mute', p.id); };
    const slow = selectEl([['Чат: без лимита', '0'], ['Чат: 5 с', '5'], ['Чат: 10 с', '10'], ['Чат: 30 с', '30']], p.chat_slow);
    slow.classList.add('small');
    const applySlow = btn('🐢 Применить', 'alt'); applySlow.classList.add('small');
    applySlow.onclick = function () { adminAct('slow', p.id, slow.value); };
    row.append(nm, kick, ban, host, mute, slow, applySlow); d.append(row);
  });
  const bans = current.bans || [];
  if (bans.length) {
    d.append(h2('Забанены'));
    bans.forEach(function (b) {
      const row = div('adminrow');
      row.append(div('muted', b.name + ' (' + b.short + '…)'));
      const un = btn('Разбанить', 'alt'); un.classList.add('small');
      un.onclick = function () { adminAct('unban', null, b.client); };
      row.append(un); d.append(row);
    });
  }
  return d;
}

function renderSettingsCard() {
  const c = div('card');
  c.append(h2('⚙️ Настройки комнаты'));
  const st = current.settings;
  if (!current.you.is_host) {
    c.append(div('muted', 'Сложность: ' + DIFF_LABEL[st.difficulty] + ' • Волн: ' + st.max_waves +
      ' • Таймер: ' + st.turn_timer + ' с • Золото: ' + st.start_gold +
      (st.has_password ? ' • 🔒 пароль' : '')));
    return c;
  }
  if (current.phase !== 'lobby') {
    c.append(div('muted', 'Настройки меняются в лобби. Сейчас: ' + DIFF_LABEL[st.difficulty] +
      ', волн ' + st.max_waves + ', таймер ' + st.turn_timer + ' с, золото ' + st.start_gold +
      (st.has_password ? ', пароль установлен' : ', без пароля') + '.'));
    return c;
  }
  const row = div('row');
  row.append(div('muted', 'Сложность'), selectEl([['Лёгкая', 'easy'], ['Обычная', 'normal'], ['Сложная', 'hard']], st.difficulty, 'set-diff'));
  row.append(div('muted', 'Волн'), selectEl([['2', '2'], ['3', '3'], ['4', '4']], st.max_waves, 'set-waves'));
  row.append(div('muted', 'Таймер'), selectEl([['15 с', '15'], ['30 с', '30'], ['45 с', '45'], ['60 с', '60'], ['90 с', '90']], st.turn_timer, 'set-timer'));
  row.append(div('muted', 'Золото'), selectEl([['0', '0'], ['50', '50'], ['100', '100'], ['200', '200']], st.start_gold, 'set-gold'));
  c.append(row);
  const prow = div('row');
  const pass = document.createElement('input');
  pass.id = 'set-pass'; pass.type = 'password'; pass.maxLength = 24;
  pass.placeholder = st.has_password ? 'Новый пароль (пусто — не менять)' : 'Пароль комнаты (необязательно)';
  pass.style.flex = '1';
  const clear = document.createElement('label'); clear.className = 'muted';
  const cb = document.createElement('input'); cb.type = 'checkbox'; cb.id = 'set-clear';
  clear.append(cb, document.createTextNode(' убрать пароль'));
  prow.append(pass, clear); c.append(prow);
  const save = btn('Сохранить настройки', 'alt');
  save.onclick = async function () {
    if (busy) return; busy = true; showError('');
    try {
      const payload = {
        token: token,
        difficulty: $('set-diff').value,
        max_waves: parseInt($('set-waves').value, 10),
        turn_timer: parseInt($('set-timer').value, 10),
        start_gold: parseInt($('set-gold').value, 10),
        clear_password: $('set-clear').checked
      };
      const pv = $('set-pass').value.trim();
      if (pv) payload.password = pv;
      const d = await post('/api/settings', payload);
      current = d.state; lastVersion = d.state.version; render();
    } catch (e) {
      showError(e.message);
    } finally {
      busy = false;
    }
  };
  c.append(save);
  const linkRow = div('row');
  const link = document.createElement('code'); link.className = 'code'; link.textContent = current.join_url;
  const copy = btn('Скопировать ссылку', 'alt'); copy.classList.add('small');
  copy.onclick = function () { copyText(current.join_url, copy); };
  linkRow.append(link, copy); c.append(linkRow);
  c.append(div('muted', 'Пароль и настройки действуют на новую игру и новых игроков.'));
  return c;
}

function renderReadyCard() {
  const c = div('card');
  const readyCount = current.players.filter(function (p) { return p.ready; }).length;
  c.append(h2('✅ Готовность (' + readyCount + '/' + current.players.length + ')'));
  c.append(div('muted', 'Когда готовы все и в комнате минимум 2 игрока, игра начнётся автоматически. Хост может начать принудительно.'));
  const b = btn(current.you.ready ? 'Я не готов' : 'Я готов', current.you.ready ? 'alt' : '');
  b.onclick = async function () {
    if (busy) return;
    busy = true; showError('');
    try {
      const d = await post('/api/ready', { token: token, ready: !current.you.ready });
      current = d.state; lastVersion = d.state.version; render();
    } catch (e) {
      showError(e.message);
    } finally {
      busy = false;
    }
  };
  c.append(b);
  return c;
}

function renderLastRoomCard(last) {
  const c = div('card');
  c.append(h2('🔙 Последняя комната'));
  const top = div('row');
  top.append(div('tag', last.mode_label || (last.mode === 'pvp' ? '⚔️ PvP' : '🤝 Команда')));
  top.append(div('tag', '🔢 ' + last.code));
  if (last.at) top.append(div('muted', fmtWhen(last.at)));
  c.append(top);
  c.append(div('muted', 'Ты был: ' + (last.name || 'Игрок') + ' · ' + (CLASSES[last.cls] ? last.cls : 'Воин') + (last.has_password ? ' · 🔒 пароль' : '')));
  const row = div('row');
  const back = btn('Вернуться');
  back.onclick = function () { returnToLastRoom(last); };
  const forget = btn('Забыть', 'alt'); forget.classList.add('small');
  forget.onclick = function () {
    if (confirm('Убрать карточку последней комнаты?')) forgetLastRoom();
  };
  row.append(back, forget);
  c.append(row);
  c.append(div('muted', 'Сначала попробуем код возврата. Если комната уже закрыта — зайдёшь заново.'));
  return c;
}

function renderJoin(errMsg, keep) {
  const v = $('view'); v.innerHTML = '';
  v.append(h1('Подключение к мультиплееру'));
  v.append(div('muted', 'Режим: ' + MODE_LABEL + '. Игроков: от ' + 2 + ' до 4.'));
  if (errMsg) v.append(div('err', errMsg));
  const last = loadLastRoom();
  if (last) v.append(renderLastRoomCard(last));
  const c = div('card');
  c.append(h2('Имя'));
  const name = document.createElement('input'); name.id = 'join-name'; name.maxLength = 16;
  name.value = keep && keep.name !== undefined ? keep.name : savedName;
  name.placeholder = 'Как тебя зовут?'; name.style.width = '100%';
  c.append(name);
  c.append(h2('Класс'));
  let selected = (keep && keep.cls && CLASSES[keep.cls]) ? keep.cls
    : (savedClass && CLASSES[savedClass] ? savedClass : 'Воин');
  const grid = div('grid');
  Object.keys(CLASSES).forEach(function (cls) {
    const cfg = CLASSES[cls];
    const b = btn('', 'classbtn' + (cls === selected ? ' sel' : ''));
    b.append(div('', cls + '  (HP ' + cfg.hp + ', ⚔️' + cfg.attack + ', 🛡️' + cfg.defense + ')'));
    b.append(div('muted', '✨ ' + cfg.ability + ': ' + cfg.ability_desc));
    b.onclick = function () { selected = cls; grid.querySelectorAll('.classbtn').forEach(function (x) { x.classList.remove('sel'); }); b.classList.add('sel'); };
    grid.append(b);
  });
  c.append(grid);
  c.append(h2('Пароль комнаты'));
  const pass = document.createElement('input'); pass.id = 'join-pass'; pass.type = 'password'; pass.maxLength = 24;
  pass.placeholder = 'Если хост поставил пароль'; pass.style.width = '100%';
  pass.value = keep && keep.password ? keep.password : '';
  c.append(pass);
  const go = btn('Присоединиться');
  go.style.marginTop = '10px';
  go.onclick = async function () {
    const nm = name.value.trim() || 'Игрок';
    localStorage.setItem('mp_name', nm); localStorage.setItem('mp_class', selected);
    savedName = nm; savedClass = selected;
    go.disabled = true;
    try {
      const d = await post('/api/join', { client: client, name: nm, 'class': selected, password: pass.value });
      saveSession(d);
    } catch (e) {
      renderJoin(e.message, { name: nm, cls: selected, password: pass.value, focus: /парол/i.test(e.message) ? 'pass' : '' });
    }
  };
  name.addEventListener('keydown', function (e) { if (e.key === 'Enter') go.click(); });
  pass.addEventListener('keydown', function (e) { if (e.key === 'Enter') go.click(); });
  c.append(go);
  v.append(c);

  const rc = div('card');
  rc.append(h2('🔑 Уже играл?'));
  rc.append(div('muted', 'Введи код возврата, который показывался в игре. Имя и класс восстановятся.'));
  const rrow = div('row');
  const rcode = document.createElement('input'); rcode.id = 'join-resume'; rcode.maxLength = 8;
  rcode.placeholder = 'Код возврата'; rcode.style.flex = '1';
  const rbtn = btn('Вернуться', 'alt');
  rbtn.onclick = async function () {
    const code = rcode.value.trim();
    if (!code) { renderJoin('Введи код возврата.', { name: name.value, cls: selected, password: pass.value, focus: 'resume' }); return; }
    rbtn.disabled = true;
    try {
      const d = await post('/api/join', { client: client, resume: code });
      savedName = d.state.you.name; localStorage.setItem('mp_name', savedName);
      saveSession(d);
    } catch (e) {
      renderJoin(e.message, { name: name.value, cls: selected, password: pass.value, focus: 'resume' });
    }
  };
  rcode.addEventListener('keydown', function (e) { if (e.key === 'Enter') rbtn.click(); });
  rrow.append(rcode, rbtn); rc.append(rrow); v.append(rc);
  v.append(renderProfileCard());
  v.append(div('muted', 'Ссылку/QR показывает компьютер, на котором запущена игра.'));
  if (keep && keep.focus) {
    const target = $(keep.focus === 'pass' ? 'join-pass' : (keep.focus === 'resume' ? 'join-resume' : 'join-name'));
    if (target) setTimeout(function () { target.focus(); }, 30);
  }
}

function renderLobby() {
  const v = $('view'); v.innerHTML = '';
  v.append(h1(MODE_LABEL + ' — лобби'));
  v.append(div('muted', 'Хост: ' + (current.players.filter(function (p) { return p.is_host; })[0] || {}).name + '. Нужно минимум 2 игрока.'));
  const c = div('card'); c.append(h2('Игроки (' + current.players.length + '/' + current.max_players + ')')); renderPlayers(c, true); v.append(c);
  v.append(renderReadyCard());
  v.append(renderSettingsCard());
  if (current.you.is_host) {
    const start = btn('Начать игру');
    start.disabled = !current.can_start;
    start.onclick = async function () { start.disabled = true; try { const d = await post('/api/start', { token: token }); current = d.state; lastVersion = d.state.version; render(); } catch (e) { showError(e.message); start.disabled = false; } };
    v.append(start);
    if (!current.can_start) v.append(div('muted', 'Пригласи ещё хотя бы одного игрока по QR.'));
  } else {
    v.append(div('muted', 'Ждём, когда хост начнёт игру.'));
  }
  v.append(div('err', ''));
  const lc = div('card'); lc.append(h2('Журнал')); renderLogInto(lc); v.append(lc);
  renderChat(v);
}

function actionLabel(a) {
  const m = { attack: 'Атака', ability: 'Способность', potion: 'Зелье', guard: 'Защита', skip: 'Пропуск' };
  return m[a] || '';
}

function renderBattle() {
  const v = $('view'); v.innerHTML = '';
  const title = MODE === 'team' ? ('Волна ' + current.wave + '/' + current.max_waves + ' — ' + (current.enemies.length ? 'бой' : '')) : ('PvP — раунд ' + current.turn);
  v.append(h1(title));
  v.append(div('muted', 'Твой ход' + (current.you.acted ? ' принят.' : ' — выбери действие.') +
    ' • На ход: ' + current.settings.turn_timer + ' с.'));
  const pc = div('card'); pc.append(h2('Игроки')); renderPlayers(pc, true); v.append(pc);
  if (MODE === 'team' && current.enemies.length) {
    const ec = div('card'); ec.append(h2('Враги'));
    const g = div('grid');
    current.enemies.forEach(function (e) {
      const c = div('card enemy' + (e.alive ? '' : ' dead'));
      const top = div('row');
      top.append(div('', e.name));
      if (e.is_boss) top.append(div('tag boss', 'БОСС'));
      if (e.enraged) top.append(div('tag enraged', 'ЯРОСТЬ'));
      c.append(top);
      c.append(div('muted', 'HP ' + e.hp + '/' + e.max_hp + '  ⚔️' + e.attack + '  🛡️' + e.defense));
      c.append(bar('hp', e.hp, e.max_hp));
      if (e.is_boss && e.boss_desc) c.append(div('muted', e.boss_desc));
      g.append(c);
    });
    ec.append(g); v.append(ec);
  }
  const ac = div('card'); ac.append(h2('Действие'));
  if (!current.you.alive) {
    ac.append(div('muted', '💀 Ты выбыл. Можно наблюдать за боем.'));
  } else {
    if (current.you.acted) {
      ac.append(div('muted', '✅ Ход принят: ' + actionLabel(current.you.action) +
        '. Ждём: ' + (current.waiting_for.join(', ') || 'всех') +
        '. Можно изменить ход, пока не сходили все.'));
    }
    const row = div('row');
    const sel = document.createElement('select'); sel.id = 'target';
    const targets = MODE === 'team' ? current.enemies.filter(function (e) { return e.alive; }) : current.players.filter(function (p) { return p.alive && p.id !== current.you.id; });
    sel.append(new Option('Цель…', ''));
    targets.forEach(function (t) { sel.append(new Option(t.name, t.id)); });
    if (current.you.target) sel.value = current.you.target;
    row.append(sel);
    const attack = btn('⚔️ Атака');
    attack.onclick = function () { act('attack'); };
    const ability = btn('✨ ' + current.you.ability);
    ability.disabled = current.you.ability_cd > 0 || current.you.mana < current.you.ability_mana;
    ability.title = current.you.ability_desc;
    ability.onclick = function () { act('ability'); };
    const potion = btn('🧪 Зелье (' + current.you.potions + ')', 'alt');
    potion.disabled = current.you.potions <= 0;
    potion.onclick = function () { act('potion'); };
    const guard = btn('🛡️ Защита', 'alt'); guard.onclick = function () { act('guard'); };
    const skip = btn('⏭️ Пропустить', 'alt'); skip.onclick = function () { act('skip'); };
    row.append(attack, ability, potion, guard, skip); ac.append(row);
    ac.append(div('muted', 'Способность: ' + current.you.ability_desc + (current.you.ability_cd ? ' | перезарядка: ' + current.you.ability_cd : '') + (current.you.ability_mana ? ' | мана: ' + current.you.ability_mana : '')));
  }
  v.append(ac); v.append(div('err', ''));
  const lc = div('card'); lc.append(h2('Журнал')); renderLogInto(lc); v.append(lc);
  renderChat(v);
}

function renderWaveClear() {
  const v = $('view'); v.innerHTML = '';
  v.append(h1('🏆 Волна ' + current.wave + '/' + current.max_waves + ' пройдена!'));
  v.append(div('muted', 'Передышка. Можно передать ресурсы и золото союзникам.'));
  const pc = div('card'); pc.append(h2('Игроки')); renderPlayers(pc, true); v.append(pc);
  const tc = div('card'); tc.append(h2('Передать союзнику'));
  const row = div('row');
  const to = document.createElement('select'); to.id = 'tr-to';
  current.players.forEach(function (p) { if (p.id !== current.you.id) to.append(new Option(p.name, p.id)); });
  const kind = document.createElement('select'); kind.id = 'tr-kind';
  kind.append(new Option('Ресурс', 'resource'), new Option('Золото', 'gold'));
  const res = document.createElement('select'); res.id = 'tr-res';
  Object.keys(current.you.resources).forEach(function (r) { res.append(new Option(r + ' x' + current.you.resources[r], r)); });
  const amt = document.createElement('input'); amt.id = 'tr-amt'; amt.type = 'number'; amt.min = '1'; amt.value = '1';
  const send = btn('Передать', 'alt');
  kind.onchange = function () { res.style.display = kind.value === 'gold' ? 'none' : ''; };
  send.onclick = async function () {
    if (busy) return; busy = true;
    try { const d = await post('/api/transfer', { token: token, to: to.value, kind: kind.value, resource: res.value, amount: parseInt(amt.value, 10) || 0 }); current = d.state; lastVersion = d.state.version; render(); }
    catch (e) { showError(e.message); } finally { busy = false; }
  };
  row.append(to, kind, res, amt, send); tc.append(row); v.append(tc);
  if (current.you.is_host) {
    const next = btn('Следующая волна');
    next.onclick = async function () { next.disabled = true; try { const d = await post('/api/next_wave', { token: token }); current = d.state; lastVersion = d.state.version; render(); } catch (e) { showError(e.message); next.disabled = false; } };
    v.append(next);
  } else {
    v.append(div('muted', 'Ждём, когда хост начнёт следующую волну.'));
  }
  v.append(div('err', ''));
  const lc = div('card'); lc.append(h2('Журнал')); renderLogInto(lc); v.append(lc);
  renderChat(v);
}

function renderGameOver() {
  const v = $('view'); v.innerHTML = '';
  let title = 'Игра окончена';
  if (current.winner === 'team') title = '🏆 Команда победила!';
  else if (current.winner === 'defeat') title = '💀 Команда пала…';
  else if (current.winner === 'Ничья') title = '🤝 Ничья!';
  else if (current.winner) title = '🏆 Победитель: ' + current.winner;
  v.append(h1(title));
  const pc = div('card'); pc.append(h2('Итоги')); renderPlayers(pc, true); v.append(pc);
  if (current.you.is_host) {
    const again = btn('Вернуться в лобби');
    again.onclick = async function () { again.disabled = true; try { const d = await post('/api/restart', { token: token }); current = d.state; lastVersion = d.state.version; render(); } catch (e) { showError(e.message); again.disabled = false; } };
    v.append(again);
  } else {
    v.append(div('muted', 'Ждём хоста, чтобы вернуться в лобби.'));
  }
  v.append(div('err', ''));
  const lc = div('card'); lc.append(h2('Журнал')); renderLogInto(lc); v.append(lc);
  renderChat(v);
}

function render() {
  if (!current) { renderJoin(); return; }
  recordProfile();
  saveLastRoom();
  ensureMutedForRoom();
  syncMutedNames();
  chatFocusWanted = !!(document.activeElement && document.activeElement.id === 'chat');
  renameFocusWanted = renameFocusWanted || !!(document.activeElement && document.activeElement.id === 'rename-input');
  if (current.phase === 'lobby') renderLobby();
  else if (current.phase === 'battle') renderBattle();
  else if (current.phase === 'wave_clear') renderWaveClear();
  else renderGameOver();
  const v = $('view');
  if (current.shutdown) v.prepend(div('shutdown', current.shutdown));
  if (current.you && current.you.resume_code) v.append(resumeBar());
  v.append(renderProfileCard());
  if (current.you && current.you.is_host) v.append(renderAdminPanel());
  if (renameFocusWanted) {
    const inp = $('rename-input');
    if (inp) {
      inp.focus();
      const end = inp.value.length;
      inp.setSelectionRange(end, end);
    }
    renameFocusWanted = false;
  }
  chatFocusWanted = false;
}

async function act(action) {
  if (busy) return;
  const sel = $('target');
  const target = sel ? sel.value : null;
  if ((action === 'attack' || (action === 'ability' && current.you.ability_target)) && !target) { showError('Выбери цель.'); return; }
  busy = true; showError('');
  try { const d = await post('/api/action', { token: token, action: action, target: target }); current = d.state; lastVersion = d.state.version; render(); }
  catch (e) { showError(e.message); } finally { busy = false; }
}

async function poll() {
  if (!token) return;
  if (polling) return;
  polling = true;
  try {
    const d = await api('/api/state?token=' + encodeURIComponent(token));
    current = d; setStatus(true);
    if (d.version !== lastVersion) { lastVersion = d.version; render(); }
  } catch (e) {
    setStatus(false);
    if (/Сессия|404|не найдена|не найден/i.test(e.message)) { logout(); return; }
  } finally { polling = false; }
  pollTimer = setTimeout(poll, 600);
}

function startPolling() { clearTimeout(pollTimer); setStatus(true); poll(); }

(async function boot() {
  if (token) {
    try {
      const d = await api('/api/state?token=' + encodeURIComponent(token));
      current = d; lastVersion = -1; setStatus(true); render(); startPolling(); return;
    } catch (e) {
      token = ''; localStorage.removeItem('mp_token');
    }
  }
  renderJoin();
})();
</script>
</body>
</html>
"""


def _html_page():
    mode = _state.mode if _state is not None else "team"
    return (MOBILE_HTML
            .replace("__CLASSES_JSON__", json.dumps(CLASSES, ensure_ascii=False))
            .replace("__MODE_JSON__", json.dumps(mode)))


class _MPHTTPServer(ThreadingHTTPServer):
    # На Windows allow_reuse_address позволяет двум серверам занять один порт.
    allow_reuse_address = False
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    server_version = "TextRPGMultiplayer/1.0"

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

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 20000:
            return None, "Слишком большой запрос."
        try:
            return json.loads(self.rfile.read(length) or b"{}"), None
        except Exception:
            return None, "Плохой JSON."

    def _state_for(self, token):
        st = _state
        if st is None:
            return None, None
        p = _player_by_token_locked(st, token)
        if p is not None:
            p.last_seen = time.monotonic()
        return st, p

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            self._send(200, _html_page(), "text/html; charset=utf-8")
            return
        if path == "/qr":
            self._send(200, _qr_page_html(), "text/html; charset=utf-8")
            return
        if path == "/qr.svg":
            svg = _qr_svg_bytes(_join_url or f"http://{_primary_ip()}:{_port}/")
            if svg is None:
                self._send(503, "Установи модуль qrcode: pip install qrcode")
            else:
                self._send(200, svg, "image/svg+xml; charset=utf-8")
            return
        if path == "/favicon.ico":
            self._send(204, b"")
            return
        if path == "/api/state":
            token = qs.get("token", [""])[0]
            with _lock:
                st, p = self._state_for(token)
                if st is None:
                    self._json(503, {"error": "Сервер не запущен."})
                    return
                if p is None:
                    self._json(404, {"error": "Сессия не найдена. Обнови страницу."})
                    return
                self._json(200, _snapshot_locked(st, p))
            return
        self._send(404, "Не найдено")

    def do_POST(self):
        path = urlparse(self.path).path
        data, err = self._read_json()
        if err:
            self._json(400, {"error": err})
            return
        if path == "/api/join":
            client_id = str(data.get("client", ""))[:100]
            name = data.get("name", "")
            cls = data.get("class", "")
            password = data.get("password", "")
            resume = data.get("resume", "")
            with _lock:
                if _state is None:
                    self._json(503, {"error": "Сервер не запущен."})
                    return
                if resume:
                    p, err = _resume_locked(_state, resume, client_id)
                else:
                    p, err = _join_locked(_state, client_id, name, cls, password,
                                          self.client_address[0])
                if err:
                    self._json(409, {"error": err})
                    return
                self._json(200, {"token": p.token, "state": _snapshot_locked(_state, p)})
            return

        token = data.get("token", "")
        with _lock:
            st, p = self._state_for(token)
            if st is None:
                self._json(503, {"error": "Сервер не запущен."})
                return
            if p is None:
                self._json(404, {"error": "Сессия не найдена. Обнови страницу."})
                return
            try:
                if path == "/api/start":
                    err = _start_locked(st, p)
                elif path == "/api/next_wave":
                    err = _next_wave_locked(st, p)
                elif path == "/api/action":
                    err = _submit_action_locked(st, p, data.get("action", ""), data.get("target"))
                elif path == "/api/transfer":
                    err = _transfer_locked(st, p, data.get("to"), data.get("kind", "resource"),
                                           data.get("resource"), data.get("amount"))
                elif path == "/api/chat":
                    err = _chat_locked(st, p, data.get("text", ""))
                elif path == "/api/rename":
                    err = _rename_locked(st, p, data.get("name", ""))
                elif path == "/api/ready":
                    err = _ready_locked(st, p, data.get("ready", False))
                elif path == "/api/restart":
                    err = _restart_locked(st, p)
                elif path == "/api/settings":
                    err = _settings_locked(st, p, data)
                elif path == "/api/admin":
                    err = _admin_locked(st, p, data.get("action", ""),
                                        data.get("target"), data.get("value"))
                else:
                    self._json(404, {"error": "Не найдено"})
                    return
                if err:
                    self._json(400, {"error": err})
                    return
                self._json(200, {"ok": True, "state": _snapshot_locked(st, p)})
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "Внутренняя ошибка сервера."})


def _submit_action_locked(st, p, action, target):
    if st.phase != "battle":
        return "Сейчас не бой."
    if not p.alive:
        return "Ты уже выбыл из боя."
    if action not in ("attack", "ability", "potion", "guard", "skip"):
        return "Неизвестное действие."
    changed = p.action is not None
    if action == "attack":
        t = _valid_target_locked(st, p, target)
        if t is None:
            return "Выбери живую цель."
        target = t.id
    elif action == "ability":
        cfg = CLASSES[p.cls]
        if p.ability_cd > 0:
            return f"Способность перезаряжается: {p.ability_cd}."
        if p.mana < cfg["mana_cost"]:
            return f"Не хватает маны: нужно {cfg['mana_cost']}."
        if cfg["needs_target"]:
            t = _valid_target_locked(st, p, target)
            if t is None:
                return "Выбери живую цель."
            target = t.id
        else:
            target = None
    elif action == "potion":
        if p.potions <= 0:
            return "Зелий нет."
        target = None
    else:
        target = None
    p.action = action
    p.target = target
    p.last_seen = time.monotonic()
    if changed:
        _add_log_locked(st, f"✏️ {p.name} изменил ход.")
    else:
        st.version += 1
    _resolve_if_ready_locked(st)
    return None


def start_server(mode="team"):
    global _state, _server, _port, _join_url, _tick_thread
    if mode not in ("team", "pvp"):
        raise ValueError("mode must be 'team' or 'pvp'")
    with _lock:
        if _server is not None:
            return _port
        _state = MPState(mode)
        _stop_event.clear()
        httpd = None
        port = 0
        last_err = None
        for candidate in PORT_RANGE:
            try:
                httpd = _MPHTTPServer(("0.0.0.0", candidate), _Handler)
                port = candidate
                break
            except OSError as e:
                last_err = e
                httpd = None
        if httpd is None:
            _state = None
            raise RuntimeError(f"Не удалось занять порт: {last_err}")
        _server = httpd
        _port = port
        _join_url = f"http://{_primary_ip()}:{port}/"
        threading.Thread(target=httpd.serve_forever, name="mp-http", daemon=True).start()
        _tick_thread = threading.Thread(target=_tick_loop, name="mp-tick", daemon=True)
        _tick_thread.start()
        return port


def stop_server():
    global _state, _server, _port, _join_url, _tick_thread
    with _lock:
        httpd = _server
        _server = None
    _stop_event.set()
    if httpd is not None:
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    with _lock:
        _state = None
        _port = 0
        _join_url = ""
        _tick_thread = None


def shutdown_server(delay=3.0):
    with _lock:
        st = _state
        if st is not None:
            st.shutdown_message = "🛑 Сервер останавливается. Спасибо за игру!"
            st.version += 1
    try:
        time.sleep(max(0.0, delay))
    except Exception:
        pass
    stop_server()


def multiplayer_menu(mode="team"):
    if mode not in ("team", "pvp"):
        mode = "team"
    try:
        port = start_server(mode)
    except Exception as e:
        print(f"❌ Не удалось запустить мультиплеер: {e}")
        return
    url = f"http://{_primary_ip()}:{port}/"
    print("\n" + "=" * 62)
    print(f"🌐 МУЛЬТИПЛЕЕР: {_mode_label(mode)}")
    print("=" * 62)
    print("1. Игроки подключаются по QR или вводят адрес в браузере телефона.")
    print("2. Компьютер откроет страницу хоста в браузере автоматически.")
    print("3. Игроки отмечают готовность; когда готовы все — игра начнётся сама.")
    print(f"\nАдрес для ручного ввода: {url}")
    print("⚠️  Мультиплеер не трогает одиночные сейвы: у героев отдельные статы.\n")

    lines = qr_ansi_lines(url)
    if lines:
        _enable_ansi()
        print("\n".join(lines))
        print()
    else:
        print("⚠️  Модуль qrcode не найден — QR в консоли не нарисовать.")
        print("    Установи: pip install qrcode\n")

    try:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    except Exception as e:
        print(f"⚠️  Не удалось открыть браузер: {e}")

    print("\nСервер работает. Введи stop и нажми Enter, чтобы остановить его и вернуться в меню.")
    print("Пустой Enter оставляет сервер работать. Команда status покажет состояние комнаты.")
    stopped = False
    while True:
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd == "stop":
            with _lock:
                st = _state
                count = len(st.players) if st is not None else 0
            if count:
                print(f"⏳ Останавливаю сервер: {count} игрок(ов) получат уведомление (около 3 секунд)...")
            else:
                print("⏳ Останавливаю сервер...")
            shutdown_server(3.0)
            stopped = True
            print("🌐 Сервер мультиплеера остановлен.")
            break
        if cmd in ("", "help", "?"):
            print("Сервер работает. Введи stop и нажми Enter для остановки. Пустой Enter ничего не меняет.")
        elif cmd in ("status", "st"):
            with _lock:
                st = _state
                if st is None:
                    print("Сервер уже остановлен.")
                else:
                    host = st.players.get(st.host_id)
                    print(f"Порт: {port} • Игроков: {len(st.players)}/{MAX_PLAYERS} • Хост: "
                          f"{host.name if host else '—'} • Фаза: {st.phase} • Код комнаты: {st.room_code}")
        else:
            print("Неизвестная команда. Доступно: stop — остановить, status — состояние.")
    if not stopped:
        shutdown_server(1.0)
        print("🌐 Сервер мультиплеера остановлен.")



