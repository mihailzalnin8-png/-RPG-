import random
import json
import os
import sys
import datetime

try:
    import phone_server
except Exception:
    phone_server = None

try:
    import multiplayer
except Exception:
    multiplayer = None

SAVE_FILE = "save.json"
GLOBAL_FILE = "global_progress.json"
HARDCORE_SAVE = "hardcore_save.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

# Защита брони (единая таблица для боя и магазина)
ARMOR_DEF = {"Рваная рубаха": 0, "Кожаная куртка": 5, "Кольчуга": 15, "Стальные латы": 25,
             "Мифриловая броня": 40, "Тыквенный шлем": 50, "Шапка Санты": 50, "Броня Бога": 100}
SHOP_WEAPONS = {"3": ("Стальной меч", 200, 10), "4": ("Секира", 500, 20), "5": ("Клинок Судьбы", 1500, 35)}
SHOP_ARMORS = {"6": ("Кожаная куртка", 150), "7": ("Кольчуга", 300), "8": ("Мифриловая броня", 800)}

def update_quest_progress(player, q_type, amount=1):
    gd = load_global_progress()
    changed = False
    quests = gd.get("quests")
    for q in (quests if isinstance(quests, list) else []):
        if q["type"] == q_type and not q["done"]:
            q["progress"] += amount
            changed = True
    for c in gd.get("guild_contracts", []):
        if c["type"] == q_type and c["progress"] < c["target"]:
            c["progress"] += amount
            changed = True
    if changed:
        save_global_progress(gd)
# --- ПРОВЕРКА ПРАЗДНИКОВ ---
def is_halloween():
    today = datetime.date.today()
    year = today.year
    halloween = datetime.date(year, 10, 31)
    start_date = halloween - datetime.timedelta(days=7)
    end_date = halloween + datetime.timedelta(days=7)
    return start_date <= today <= end_date

def is_christmas():
    today = datetime.date.today()
    year = today.year
    christmas = datetime.date(year, 12, 25)
    start_date = christmas - datetime.timedelta(days=7)
    end_date = christmas + datetime.timedelta(days=14)
    return start_date <= today <= end_date

def is_easter():
    today = datetime.date.today()
    if today.month == 4 and 1 <= today.day <= 10:
        return True
    return False

def is_september_first():
    today = datetime.date.today()
    if (today.month == 8 and today.day >= 25) or (today.month == 9 and today.day <= 8):
        return True
    return False

def is_any_holiday():
    return HALLOWEEN_MODE or CHRISTMAS_MODE or EASTER_MODE or SEPTEMBER_MODE

def is_birthday(gd):
    if not gd.get("birthday"): return False
    today = datetime.date.today()
    birth = gd["birthday"]
    
    if f"{today.day:02d}.{today.month:02d}" == birth and is_any_holiday():
        gd["birthday_postponed"] = True
        save_global_progress(gd)
        return False
        
    if f"{today.day:02d}.{today.month:02d}" == birth and not is_any_holiday():
        gd["birthday_postponed"] = False
        save_global_progress(gd)
        return True
        
    if gd.get("birthday_postponed") and not is_any_holiday():
        gd["birthday_postponed"] = False
        save_global_progress(gd)
        return True
        
    return False

HALLOWEEN_MODE = is_halloween()
CHRISTMAS_MODE = is_christmas()
EASTER_MODE = is_easter()
SEPTEMBER_MODE = is_september_first()

# --- ГЛОБАЛЬНЫЙ ФЛАГ МУСОРА ---
MUSOR_MODE = False

_original_print = print
_original_input = input

def _web_session():
    return phone_server.current_session() if phone_server else None

def print(*args, **kwargs):
    sess = _web_session()
    if MUSOR_MODE:
        if sess is not None:
            sess.write("Musor drop\n")
        else:
            _original_print("Musor drop")
    elif sess is not None:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        sess.write(sep.join(str(a) for a in args) + end)
    else:
        _original_print(*args, **kwargs)

def input(prompt=""):
    sess = _web_session()
    if MUSOR_MODE:
        if sess is not None:
            sess.write("Musor drop >>> ")
            return sess.read()
        return _original_input("Musor drop >>> ")
    if sess is not None:
        if prompt:
            sess.write(str(prompt))
        return sess.read()
    return _original_input(prompt)

def clear_screen():
    sess = _web_session()
    if sess is not None:
        sess.clear()
    else:
        os.system('cls' if os.name == 'nt' else 'clear')

# --- ФУНКЦИИ ГЛОБАЛЬНОГО ПРОГРЕССА ---

def default_global():
    return {
        "game_completed": False, "last_spin": None, "last_quest_date": None,
        "workers": {}, "quests": [], "secret_boss_unlocked": False, "last_login": None,
        "bored_debuff": 0, "vip_unlocked": False, "candies": 0,
        "snowflakes": 0, "eggs": 0, "fives": 0, "candles": 0,
        "birthday": None, "birthday_postponed": False,
        "guild_points": 0, "guild_contracts": [], "guild_perks": [],
        "camp_built": False, "camp_resources": {},
        "walls_built": False, "hunter_quest_done": False,
        "mine_built": False, "last_mine_claim": None,
        "farm_built": False, "last_farm_claim": None, "forge_built": False,
        "infinity_shards": 0, "nightmare_unlocked": False,
        "fountain_built": False, "last_fountain_claim": None,
        "armory_built": False,
        "training_built": False, "last_training_claim": None,
        "hermit_built": False, "last_hermit_claim": None,
        "magic_tower_built": False, "training_room_built": False,
        "hospital_built": False, "library_built": False, "pool_built": False, "last_pool_claim": None, "pool_buffs": 0,
        "mine_lvl": 1, "farm_lvl": 1, "fountain_lvl": 1, "armory_lvl": 1, "forge_lvl": 1,
        "training_lvl": 1, "hospital_lvl": 1, "library_lvl": 1, "pool_lvl": 1
    }

def load_global_progress():
    if not os.path.exists(GLOBAL_FILE):
        return default_global()
    try:
        with open(GLOBAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        base = default_global()
        base.update(data)
        return base
    except Exception:
        return default_global()

def save_global_progress(data):
    try:
        with open(GLOBAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        _original_print(f"❌ Ошибка сохранения глобального прогресса: {e}")

# --- КЛАССЫ ПЕРСОНАЖЕЙ ---

class Player:
    def __init__(self, name, char_class, hardcore=False, mega_hard=False, nightmare=False):
        self.name = name
        self.char_class = char_class
        self.hardcore = hardcore
        self.mega_hard = mega_hard
        self.nightmare = nightmare
        self.level = 1
        self.exp = 0
        self.exp_to_next = 100
        self.gold = 50
        self.crystals = 0
        self.inventory = {"Зелье лечения": 2, "Свиток Огня": 1, "Свиток Воскрешения": 0, "Свиток Телепорта": 0, "Свиток Молнии": 0, "Вода": 0, "Линукс": 0, "Конфета": 0}
        self.resources = {}
        
        if self.hardcore or self.mega_hard:
            self.inventory_limit = 15
        else:
            self.inventory_limit = 25
        
        self.weapon = "Кулаки"
        self.armor = "Рваная рубаха"
        self.accessory = "Нет"
        
        self.max_hp = 100
        self.hp = 100
        self.attack = 10
        self.defense = 5
        self.mana = 0
        self.max_mana = 0
        
        self.is_blocking = False
        self.debuffs = {} 
        self.used_codes = []
        self.completed_locations = []
        self.subclass = None 
        self.arena_level = 0 
        self.tower_floor = 0
        self.sans_mode = False
        
        self.upgrades = {"hp": 0, "attack": 0, "defense": 0, "mana": 0}
        self.skeleton_hp = 0
        self.damage_reduction = 0.0
        self.paladin_hit_count = 0
        self.has_bag = False
        self.rage = 0
        self.god_mode_battles = 0
        self.owned_items = []
        self.boss_rush_best = 0

        self.setup_class()

    def setup_class(self):
        if self.char_class == "Воин":
            self.max_hp = 150; self.hp = 150; self.attack = 15; self.defense = 10; self.weapon = "Тяжелый топор"
        elif self.char_class == "Маг":
            self.max_hp = 100; self.hp = 100; self.attack = 10; self.defense = 3; self.max_mana = 50; self.mana = 50; self.weapon = "Посох огня"
        elif self.char_class == "Разбойник":
            self.max_hp = 80; self.hp = 80; self.attack = 14; self.defense = 6; self.weapon = "Кинжалы"
        elif self.char_class == "Танк":
            self.max_hp = 250; self.hp = 250; self.attack = 6; self.defense = 20; self.weapon = "Огромный щит"
        elif self.char_class == "Паладин":
            self.max_hp = 180; self.hp = 180; self.attack = 10; self.defense = 12; self.weapon = "Святая булава"
        elif self.char_class == "Некромант":
            self.max_hp = 90; self.hp = 90; self.attack = 12; self.defense = 4; self.max_mana = 60; self.mana = 60; self.weapon = "Посох душ"
        elif self.char_class == "Берсерк":
            self.max_hp = 120; self.hp = 120; self.attack = 20; self.defense = 2; self.weapon = "Два топора"
        elif self.char_class == "Ассасин":
            self.max_hp = 70; self.hp = 70; self.attack = 18; self.defense = 5; self.weapon = "Скрытые клинки"
        elif self.char_class == "Повелитель Времени":
            self.max_hp = 110; self.hp = 110; self.attack = 12; self.defense = 5; self.max_mana = 80; self.mana = 80; self.weapon = "Посох Хроноса"
        else:
            self.char_class = "Воин"; self.setup_class()

    def is_alive(self):
        return self.hp > 0

    def take_damage(self, dmg):
        if self.sans_mode:
            print("💨 Ты уворачиваешься! (Режим Санса)")
            return 0

        if self.char_class == "Ассасин" and random.random() < 0.15:
            print("💨 (Пассивка Ассасина) Ты уклоняешься от атаки!")
            return 0

        armor_def = ARMOR_DEF.get(self.armor, 0)

        actual_dmg = max(1, dmg - self.defense - armor_def)
        
        # Множители сложности (хардкор/мега/кошмар) уже учтены в атаке врага (см. Enemy.__init__)
        if self.char_class == "Маг":
            actual_dmg = int(actual_dmg * 1.2)
            print("(Маг не носит броню! +20% урона)")
        if self.is_blocking:
            actual_dmg = int(actual_dmg * 0.3)
            print("Ты блокируешь удар щитом! Урон снижен.")
            self.is_blocking = False

        if self.damage_reduction > 0:
            reduced = int(actual_dmg * (1 - self.damage_reduction))
            print(f"🏗️ Стены базы снижают урон на {int(self.damage_reduction*100)}%! ({actual_dmg} -> {reduced})")
            actual_dmg = max(1, reduced)
            
        self.hp -= actual_dmg
        self.rage = min(100, self.rage + 10)
        print(f"Ты получаешь {actual_dmg} урона. (HP: {self.hp}/{self.max_hp}) | 🔥 Ярость: {self.rage}/100")
        return actual_dmg

    def process_debuffs(self):
        if self.char_class == "Танк":
            return
        for name, data in list(self.debuffs.items()):
            if data["turns"] > 0:
                print(f"💀 Эффект [{name}]: ты теряешь {data['dmg']} HP.")
                self.hp -= data["dmg"]
                data["turns"] -= 1
                if data["turns"] == 0:
                    print(f"✅ Эффект [{name}] закончился.")
                    del self.debuffs[name]

    def heal(self, amount):
        self.hp = min(self.max_hp, self.hp + amount)
        print(f"Ты восстановил {amount} HP. (HP: {self.hp}/{self.max_hp})")

    def restore_mana(self, amount):
        self.mana = min(self.max_mana, self.mana + amount)
        print(f"Ты восстановил {amount} маны. (MP: {self.mana}/{self.max_mana})")

    def gain_exp(self, amount):
        if self.mega_hard or self.nightmare: amount = int(amount * 1.5)
        self.exp += amount
        print(f"Получено {amount} опыта.")
        while self.exp >= self.exp_to_next:
            self.level_up()

    def level_up(self):
        self.level += 1
        self.exp -= self.exp_to_next
        self.exp_to_next = int(self.exp_to_next * 1.5)
        self.max_hp += 20
        self.hp = self.max_hp
        self.attack += 3
        self.defense += 2
        if self.char_class in ["Маг", "Некромант", "Повелитель Времени"]:
            self.max_mana += 10
            self.mana = self.max_mana
        print(f"=== УРОВЕНЬ ПОВЫШЕН! Теперь ты {self.level} уровня! ===")
        
        if self.level == 5 and not self.subclass:
            print("\n🎉 Ты достиг 5 уровня! Выбери свою ветку развития:")
            print("1. Мастер оружия (+5 к атаке навсегда)")
            print("2. Мастер защиты (+10 к защите навсегда)")
            choice = input("Твой выбор (1/2): ")
            if choice == "1":
                self.subclass = "Мастер оружия"; self.attack += 5; print("Ты стал Мастером оружия!")
            else:
                self.subclass = "Мастер защиты"; self.defense += 10; print("Ты стал Мастером защиты!")
                
    def show_stats(self):
        print(f"\n--- {self.name} ({self.char_class} - {self.subclass or 'Без ветки'}) ---")
        if self.mega_hard: print("🔥 РЕЖИМ: МЕГА-ХАРДКОР")
        elif self.hardcore: print("🔥 РЕЖИМ: ХАРДКОР")
        elif self.nightmare: print("🔥 РЕЖИМ: КОШМАР")
        if self.sans_mode: print("💀 РЕЖИМ: САНС (1 HP, уворот)")
        print(f"Уровень: {self.level} | Опыт: {self.exp}/{self.exp_to_next}")
        print(f"HP: {self.hp}/{self.max_hp} | Базовая защита: {self.defense}")
        if self.char_class in ["Маг", "Некромант", "Повелитель Времени"]: print(f"MP: {self.mana}/{self.max_mana}")
        print(f"Атака: {self.attack}")
        print(f"🗡️ Оружие: {self.weapon} | 🛡️ Броня: {self.armor} | 💍 Аксессуар: {self.accessory}")
        print(f"Золото: {self.gold} | 💎 Алмазы: {self.crystals}")
        print(f"🎒 Инвентарь: Зелья: {self.inventory.get('Зелье лечения', 0)} | Свитки Огня: {self.inventory.get('Свиток Огня', 0)} | Свитки Воскрешения: {self.inventory.get('Свиток Воскрешения', 0)} | Телепорт: {self.inventory.get('Свиток Телепорта', 0)} | Молния: {self.inventory.get('Свиток Молнии', 0)} | Вода: {self.inventory.get('Вода', 0)} | Линукс: {self.inventory.get('Линукс', 0)} | Конфеты: {self.inventory.get('Конфета', 0)} | Зелья маны: {self.inventory.get('Зелье маны', 0)}")
        print(f"Сумка: {'✅ Есть' if self.has_bag else '❌ Нет'}")
        print(f"Ресурсы: {self.resources}")
        if self.tower_floor > 0: print(f"🏰 Рекорд Башни: Этаж {self.tower_floor}")
        if self.god_mode_battles > 0: print(f"🌟 Режим Бога: {self.god_mode_battles} бой(ев)")
        if self.debuffs: print(f"Активные дебаффы: {list(self.debuffs.keys())}")

    def to_dict(self):
        return {
            "name": self.name, "char_class": self.char_class, "hardcore": self.hardcore, "mega_hard": self.mega_hard,
            "nightmare": self.nightmare,
            "level": self.level, "exp": self.exp, "exp_to_next": self.exp_to_next, "gold": self.gold,
            "crystals": self.crystals,
            "inventory": self.inventory, "resources": self.resources,
            "weapon": self.weapon, "armor": self.armor, "accessory": self.accessory,
            "max_hp": self.max_hp, "hp": self.hp, "attack": self.attack,
            "defense": self.defense, "mana": self.mana, "max_mana": self.max_mana,
            "used_codes": self.used_codes, "completed_locations": self.completed_locations,
            "subclass": self.subclass, "arena_level": self.arena_level, "tower_floor": self.tower_floor,
            "sans_mode": self.sans_mode, "inventory_limit": self.inventory_limit,
            "upgrades": self.upgrades, "has_bag": self.has_bag,
            "god_mode_battles": self.god_mode_battles,
            "owned_items": self.owned_items,
            "boss_rush_best": self.boss_rush_best
        }

    @classmethod
    def from_dict(cls, data):
        player = cls(data["name"], data["char_class"], data.get("hardcore", False), data.get("mega_hard", False), data.get("nightmare", False))
        player.level = data.get("level", 1); player.exp = data.get("exp", 0); player.exp_to_next = data.get("exp_to_next", 100)
        player.gold = data.get("gold", 50); player.crystals = data.get("crystals", 0)
        inv = {"Зелье лечения": 0, "Свиток Огня": 0, "Свиток Воскрешения": 0, "Свиток Телепорта": 0, "Свиток Молнии": 0, "Вода": 0, "Линукс": 0, "Конфета": 0}
        inv.update(data.get("inventory", {}))
        player.inventory = inv
        player.resources = data.get("resources", {})
        player.weapon = data.get("weapon", player.weapon); player.armor = data.get("armor", "Рваная рубаха"); player.accessory = data.get("accessory", "Нет")
        player.max_hp = data.get("max_hp", player.max_hp); player.hp = data.get("hp", player.hp); player.attack = data.get("attack", player.attack); player.defense = data.get("defense", player.defense)
        player.mana = data.get("mana", 0); player.max_mana = data.get("max_mana", 0)
        player.used_codes = data.get("used_codes", []); player.completed_locations = data.get("completed_locations", [])
        player.subclass = data.get("subclass", None); player.arena_level = data.get("arena_level", 0)
        player.tower_floor = data.get("tower_floor", 0)
        player.sans_mode = data.get("sans_mode", False)
        player.inventory_limit = data.get("inventory_limit", 25)
        player.upgrades = data.get("upgrades", {"hp": 0, "attack": 0, "defense": 0, "mana": 0})
        player.has_bag = data.get("has_bag", False)
        player.god_mode_battles = data.get("god_mode_battles", 0)
        player.owned_items = data.get("owned_items", [])
        player.boss_rush_best = data.get("boss_rush_best", 0)
        player.skeleton_hp = 0
        player.is_blocking = False
        player.debuffs = {}
        player.damage_reduction = 0.0
        player.paladin_hit_count = 0
        player.rage = 0
        return player


class Enemy:
    def __init__(self, name, hp, attack, defense, exp_reward, gold_reward, is_final_boss=False, drops=None, hardcore=False, mega_hard=False, nightmare=False):
        self.name = name
        if CHRISTMAS_MODE:
            if "Гоблин" in name: self.name = "Эльф-Хулиган"
            elif "Скелет" in name: self.name = "Снеговик"
            elif "Волк" in name: self.name = "Олень"
        elif HALLOWEEN_MODE:
            if "Гоблин" in name: self.name = "Зомби"
            elif "Скелет" in name: self.name = "Тыквоголовый"
            elif "Волк" in name: self.name = "Адский пёс"
        elif EASTER_MODE:
            if "Гоблин" in name: self.name = "Зайчик-Хулиган"
            elif "Скелет" in name: self.name = "Курица-Зомби"
            elif "Волк" in name: self.name = "Пасхальный Олень"
        elif SEPTEMBER_MODE:
            if "Гоблин" in name: self.name = "Школьник"
            elif "Скелет" in name: self.name = "Учитель"
            elif "Волк" in name: self.name = "Сторож"
            
        mult_hp = 3 if mega_hard else (2 if hardcore else 1)
        mult_atk = 2 if mega_hard else (1.5 if hardcore else 1)
        if nightmare: mult_atk *= 2; mult_hp *= 1.5
        
        self.hp = int(hp * mult_hp); self.max_hp = self.hp
        self.attack = int(attack * mult_atk); self.defense = defense
        self.exp_reward = exp_reward; self.gold_reward = gold_reward; self.is_final_boss = is_final_boss
        self.drops = dict(drops) if drops else {}
        self.debuffs = {}
        self.hardcore = hardcore
        self.mega_hard = mega_hard
        self.nightmare = nightmare

    def is_alive(self): return self.hp > 0
    def take_damage(self, dmg):
        actual_dmg = max(1, dmg - self.defense); self.hp -= actual_dmg
        print(f"{self.name} получает {actual_dmg} урона. (HP: {self.hp}/{self.max_hp})"); return actual_dmg
    def process_debuffs(self):
        for name, data in list(self.debuffs.items()):
            if data["turns"] > 0:
                print(f"🔥 Эффект [{name}] на {self.name}: {data['dmg']} урона.")
                self.hp -= data["dmg"]; data["turns"] -= 1
                if data["turns"] == 0: print(f"✅ Эффект [{name}] закончился."); del self.debuffs[name]
    def add_debuff(self, name, dmg, turns):
        self.debuffs[name] = {"dmg": dmg, "turns": turns}; print(f"⚡ {self.name} получает дебафф: [{name}]!")

def make_enemy(name, hp, attack, defense, exp_reward, gold_reward, is_final_boss=False, drops=None):
    def factory(player):
        return Enemy(name, hp, attack, defense, exp_reward, gold_reward, is_final_boss=is_final_boss, drops=drops, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
    factory.enemy_name = name
    return factory

def check_inventory_limit(player):
    total_items = sum(player.inventory.values())
    if not player.has_bag:
        total_items += sum(player.resources.values())
    if total_items >= player.inventory_limit:
        print(f"❌ Инвентарь полон! ({total_items}/{player.inventory_limit})")
        return False
    return True

def save_game(player):
    if not player.is_alive(): return  # мёртвого героя не сохраняем
    file = HARDCORE_SAVE if player.hardcore else SAVE_FILE
    try:
        with open(file, "w", encoding="utf-8") as f: json.dump(player.to_dict(), f, ensure_ascii=False, indent=4)
        print(f"💾 Сохранено в {'Хардкор' if player.hardcore else 'Обычный'} слот!")
    except Exception as e: print(f"❌ Ошибка: {e}")

def load_game(hardcore=False):
    file = HARDCORE_SAVE if hardcore else SAVE_FILE
    if not os.path.exists(file): return None
    try:
        with open(file, "r", encoding="utf-8") as f: return Player.from_dict(json.load(f))
    except Exception as e: print(f"❌ Ошибка: {e}"); return None

def check_sudden_death(player, delete_save=True):
    if not player.hardcore and not player.mega_hard and not player.nightmare:
        return False
    
    if random.random() < 0.01: 
        print("\n" + "!"*50)
        print("💔 ВНЕЗАПНЫЙ СЕРДЕЧНЫЙ ПРИСТУП!")
        print("Ты умер, не успев даже вскрикнуть.")
        print("Хардкор — есть хардкор.")
        print("!"*50 + "\n")
        own_file = HARDCORE_SAVE if player.hardcore else SAVE_FILE
        if delete_save and os.path.exists(own_file):
            try:
                os.remove(own_file)
                print("🔥 Сохранение УДАЛЕНО!")
            except Exception as e:
                print(f"❌ Не удалось удалить сейв: {e}")
        return True
    return False

def guild_menu(player):
    gd = load_global_progress()
    while True:
        gd = load_global_progress()
        print("\n" + "="*30)
        print("🏛️ ГИЛЬДИЯ")
        print("="*30)
        print(f"Очки гильдии: {gd.get('guild_points', 0)}")
        
        print("\n--- Контракты ---")
        if not gd.get("guild_contracts"):
            contracts = [
                {"name": "Убить 10 врагов", "type": "kill", "target": 10, "progress": 0, "reward": 5},
                {"name": "Потратить 500 золота", "type": "spend", "target": 500, "progress": 0, "reward": 5},
                {"name": "Пройти 2 локации", "type": "loc", "target": 2, "progress": 0, "reward": 10},
                {"name": "Убить 5 боссов", "type": "boss", "target": 5, "progress": 0, "reward": 15},
                {"name": "Скрафтить 3 предмета", "type": "craft", "target": 3, "progress": 0, "reward": 8},
                {"name": "Сделать 5 ставок на арене", "type": "arena", "target": 5, "progress": 0, "reward": 12},
                {"name": "Выпить 10 зелий", "type": "potion", "target": 10, "progress": 0, "reward": 6}
            ]
            gd["guild_contracts"] = contracts
            save_global_progress(gd)
            
        for i, c in enumerate(gd["guild_contracts"], 1):
            status = "✅" if c["progress"] >= c["target"] else f"[{c['progress']}/{c['target']}]"
            print(f"{i}. {c['name']} {status} (Награда: {c['reward']} очков)")
            
        print("0. Назад")
        choice = input("\nВыбор: ")
        
        if choice == "0": break
        elif choice.isdigit() and 1 <= int(choice) <= len(gd["guild_contracts"]):
            c = gd["guild_contracts"][int(choice)-1]
            if c["progress"] >= c["target"]:
                gd["guild_points"] = gd.get("guild_points", 0) + c["reward"]
                c["progress"] = 0
                save_global_progress(gd)
                print("✅ Контракт выполнен! Очки гильдии получены.")
            else:
                print("❌ Контракт еще не выполнен!")
def camp_menu(player):
    original_limit = player.inventory_limit
    first_screen = True
    last_gold = player.gold
    _g = load_global_progress()
    pending_report = workers_collect(_g) if _g.get("camp_built") else []  # пока тебя не было, рабочие трудились
    if pending_report: save_global_progress(_g)
    player.inventory_limit = 30 
    
    gd = load_global_progress()
    while True:
        gd = load_global_progress()
        
        if player.gold < last_gold:
            update_quest_progress(player, "spend", last_gold - player.gold)
            gd = load_global_progress()
        last_gold = player.gold
        # Пауза, чтобы успеть прочитать результат прошлого действия, затем чистим экран
        if not first_screen:
            input("\nНажми Enter, чтобы продолжить...")
        first_screen = False
        clear_screen()
        
        print("\n" + "="*30)
        print("🏕️ ЛАГЕРЬ")
        print("="*30)
        
        # СТАТУСЫ
        print(f"Лагерь: {'✅' if gd.get('camp_built') else '❌'} | Стены: {'✅' if gd.get('walls_built') else '❌'} | Рудник (Ур.{gd.get('mine_lvl',1)}): {'✅' if gd.get('mine_built') else '❌'}")
        print(f"Ферма (Ур.{gd.get('farm_lvl',1)}): {'✅' if gd.get('farm_built') else '❌'} | Кузница (Ур.{gd.get('forge_lvl',1)}): {'✅' if gd.get('forge_built') else '❌'}")
        print(f"Фонтан (Ур.{gd.get('fountain_lvl',1)}): {'✅' if gd.get('fountain_built') else '❌'} | Оружейная (Ур.{gd.get('armory_lvl',1)}): {'✅' if gd.get('armory_built') else '❌'}")
        print(f"Стрельбище (Ур.{gd.get('training_lvl',1)}): {'✅' if gd.get('training_built') else '❌'} | Госпиталь (Ур.{gd.get('hospital_lvl',1)}): {'✅' if gd.get('hospital_built') else '❌'}")
        print(f"Библиотека (Ур.{gd.get('library_lvl',1)}): {'✅' if gd.get('library_built') else '❌'} | Бассейн (Ур.{gd.get('pool_lvl',1)}): {'✅' if gd.get('pool_built') else '❌'}")
        print(f"Трен. зал: {'✅' if gd.get('training_room_built') else '❌'} | Хижина отшельника: {'✅' if gd.get('hermit_built') else '❌'} | Маг. башня: {'✅' if gd.get('magic_tower_built') else '❌'}")
        
        print("\n") # ОТСТУП
        print(f"Ресурсы в лагере: {gd.get('camp_resources', {})}")
        if gd.get("workers"): print("Рабочие: " + ", ".join(f"{WORKERS[r][0]} ур.{w['lvl']}" for r, w in gd["workers"].items() if r in WORKERS))
        for _line in pending_report: print("📦 " + _line)
        pending_report = []
        print("\n") # ОТСТУП
        
        # МЕНЮ
        if not gd.get("camp_built"):
            print("1. Построить лагерь (1000 золота)")
        else:
            print("1. Отдохнуть (восстановить HP)")
            print("2. Оставить ресурсы")
            print("3. Забрать ресурсы")
            
            if not gd.get("walls_built"): print("4. Построить стены (2000 золота)")
            else: print("4. [Стены уже построены]")
            
            if not gd.get("mine_built"): print("5. Построить рудник (5000 золота)")
            else: print("5. Забрать добычу из рудника")
            
            if not gd.get("farm_built"): print("6. Построить ферму (3000 золота)")
            else: print("6. Забрать урожай с фермы")
            
            if not gd.get("forge_built"): print("7. Построить кузницу (4000 золота)")
            else: print("7. Улучшить оружие в кузнице")
            
            if not gd.get("fountain_built"): print("8. Построить Фонтан (2500 золота)")
            else: print("8. Испить из Фонтана")
            
            if not gd.get("armory_built"): print("9. Построить Оружейную (3500 золота)")
            else: print("9. Зайти в Оружейную")
            
            if not gd.get("training_built"): print("10. Построить Стрельбище (3000) — +10% урона в Лесу")
            else: print("10. [Стрельбище уже построено]")
            
            if not gd.get("hospital_built"): print("11. Построить Госпиталь (4000) — зелья лечат +20 HP")
            else: print("11. [Госпиталь уже построен]")
            
            if not gd.get("library_built"): print("12. Построить Библиотеку (3500) — +20% опыта")
            else: print("12. [Библиотека уже построена]")
            
            if not gd.get("pool_built"): print("13. Построить Бассейн (5000) — бафф +20 атаки")
            else: print("13. Искупаться в Бассейне")
            
            if not gd.get("training_room_built"): print("14. Построить Тренировочный зал (2500) — +100 опыта в день")
            else: print("14. Потренироваться в Зале")
            
            if not gd.get("hermit_built"): print("15. Построить Хижину отшельника (3000) — снимает дебаффы")
            else: print("15. Поговорить с Отшельником")
            
            if not gd.get("magic_tower_built"): print("16. Построить Магическую башню (7000) — +20 макс. маны")
            else: print("16. [Магическая башня уже построена]")
            
            # УЛУЧШЕНИЯ
            if gd.get("mine_built") and gd.get("mine_lvl", 1) < 3:
                print("17. Улучшить Рудник (2000 золота)")
            if gd.get("farm_built") and gd.get("farm_lvl", 1) < 3:
                print("18. Улучшить Ферму (2500 золота)")
            if gd.get("fountain_built") and gd.get("fountain_lvl", 1) < 2:
                print("19. Улучшить Фонтан (3000 золота)")
            if gd.get("armory_built") and gd.get("armory_lvl", 1) < 2:
                print("20. Улучшить Оружейную (4000 золота)")
            print("21. 👷 Рабочие лагеря")

        print("\n0. Выйти")
        
        choice = input("\nВыбор: ")
        
        # ОБРАБОТКА ВЫБОРА
        if choice == "0": break
        
        elif choice == "21":
            if not gd.get("camp_built"): print("❌ Сначала построй лагерь!")
            else: workers_menu(player)
        
        elif choice == "1":
            if not gd.get("camp_built"):
                if player.gold >= 1000: player.gold -= 1000; gd["camp_built"] = True; save_global_progress(gd); print("✅ Лагерь построен!")
                else: print("❌ Мало золота!")
            else:
                player.hp = player.max_hp; print("✅ Ты отдохнул и восстановил все HP!")
                
        elif choice == "2":
            if not player.resources: print("❌ У тебя нет ресурсов!"); continue
            res = input("Какой ресурс оставить? ")
            if res in player.resources:
                try: amt = int(input(f"Сколько {res} оставить? "))
                except: print("❌ Введи число!"); continue
                if amt <= 0: print("❌ Количество должно быть больше нуля!")
                elif amt <= player.resources[res]:
                    player.resources[res] -= amt; gd["camp_resources"][res] = gd["camp_resources"].get(res, 0) + amt; save_global_progress(gd)
                    print(f"✅ Оставлено {amt} {res}.")
                    
        elif choice == "3":
            if not gd.get("camp_resources"): print("❌ В лагере нет ресурсов!"); continue
            res = input("Какой ресурс забрать? ")
            if res in gd["camp_resources"]:
                try: amt = int(input(f"Сколько {res} забрать? "))
                except: print("❌ Введи число!"); continue
                if amt <= 0: print("❌ Количество должно быть больше нуля!")
                elif amt <= gd["camp_resources"][res]:
                    gd["camp_resources"][res] -= amt; player.resources[res] = player.resources.get(res, 0) + amt; save_global_progress(gd)
                    print(f"✅ Забрано {amt} {res}.")
                    
        elif choice == "4":
            if not gd.get("walls_built"):
                if player.gold >= 2000: player.gold -= 2000; gd["walls_built"] = True; save_global_progress(gd); print("🏗️ Стены построены!")
                else: print("❌ Мало золота!")
            else: print("❌ Уже построено!")
            
        elif choice == "5":
            if not gd.get("mine_built"):
                if player.gold >= 5000: player.gold -= 5000; gd["mine_built"] = True; save_global_progress(gd); print("⛏️ Рудник построен!")
                else: print("❌ Мало золота!")
            else:
                today = datetime.date.today().isoformat()
                if gd.get("last_mine_claim") == today: print("❌ Рудник уже выработал норму!")
                else:
                    gd["last_mine_claim"] = today
                    lvl = gd.get("mine_lvl", 1)
                    gold_amt = 500 + (lvl - 1) * 500
                    player.gold += gold_amt; player.crystals += 1; save_global_progress(gd)
                    print(f"⛏️ Ты забрал добычу: +{gold_amt} золота, +1 Алмаз!")
                    
        elif choice == "6":
            if not gd.get("farm_built"):
                if player.gold >= 3000: player.gold -= 3000; gd["farm_built"] = True; save_global_progress(gd); print("🌾 Ферма построена!")
                else: print("❌ Мало золота!")
            else:
                today = datetime.date.today().isoformat()
                if gd.get("last_farm_claim") == today: print("❌ Урожай уже собран!")
                else:
                    gd["last_farm_claim"] = today
                    lvl = gd.get("farm_lvl", 1)
                    potions = 5 + (lvl - 1) * 5
                    player.inventory["Зелье лечения"] = player.inventory.get("Зелье лечения", 0) + potions
                    save_global_progress(gd)
                    print(f"🌾 Собрано {potions} зелий!")
                    
        elif choice == "7":
            if not gd.get("forge_built"):
                if player.gold >= 4000: player.gold -= 4000; gd["forge_built"] = True; save_global_progress(gd); print("⚒️ Кузница построена!")
                else: print("❌ Мало золота!")
            else:
                if player.weapon == "Меч Рыцаря" or player.weapon == "Меч Богов" or player.weapon == "Меч Хаоса": print("❌ Уже улучшено!")
                elif player.resources.get("Чешуя", 0) >= 3 and player.gold >= 1000:
                    player.resources["Чешуя"] -= 3; player.gold -= 1000; player.attack += 15; player.weapon = "Меч Рыцаря"
                    print("⚒️ Выкован 'Меч Рыцаря'!")
                else: print("❌ Нужно 3 Чешуи и 1000 золота.")
                
        elif choice == "8":
            if not gd.get("fountain_built"):
                if player.gold >= 2500: player.gold -= 2500; gd["fountain_built"] = True; save_global_progress(gd); print("⛲ Фонтан построен!")
                else: print("❌ Мало золота!")
            else:
                today = datetime.date.today().isoformat()
                if gd.get("last_fountain_claim") == today: print("❌ Фонтан исчерпан!")
                else:
                    gd["last_fountain_claim"] = today
                    player.hp = player.max_hp; player.mana = player.max_mana
                    lvl = gd.get("fountain_lvl", 1)
                    boost = 5 if lvl == 1 else 10
                    player.attack += boost; save_global_progress(gd)
                    print(f"⛲ Ты испил из Фонтана! +{boost} к атаке навсегда.")
                    
        elif choice == "9":
            if not gd.get("armory_built"):
                if player.gold >= 3500: player.gold -= 3500; gd["armory_built"] = True; player.defense += 10; save_global_progress(gd); print("🛡️ Оружейная построена! (+10 защиты)")
                else: print("❌ Мало золота!")
            else: print("🛡️ Ты заходишь в Оружейную. На стенах висят клинки.")
            
        elif choice == "10":
            if not gd.get("training_built"):
                if player.gold >= 3000: player.gold -= 3000; gd["training_built"] = True; save_global_progress(gd); print("🏹 Стрельбище построено!")
                else: print("❌ Мало золота!")
            else: print("🏹 Стрельбище уже построено.")
            
        elif choice == "11":
            if not gd.get("hospital_built"):
                if player.gold >= 4000: player.gold -= 4000; gd["hospital_built"] = True; save_global_progress(gd); print("🏥 Госпиталь построен!")
                else: print("❌ Мало золота!")
            else: print("🏥 Госпиталь уже построен.")
            
        elif choice == "12":
            if not gd.get("library_built"):
                if player.gold >= 3500: player.gold -= 3500; gd["library_built"] = True; save_global_progress(gd); print("📚 Библиотека построена!")
                else: print("❌ Мало золота!")
            else: print("📚 Библиотека уже построена.")
            
        elif choice == "13":
            if not gd.get("pool_built"):
                if player.gold >= 5000: player.gold -= 5000; gd["pool_built"] = True; save_global_progress(gd); print("⛲ Бассейн построен!")
                else: print("❌ Мало золота!")
            else:
                today = datetime.date.today().isoformat()
                if gd.get("last_pool_claim") == today: print("❌ Уже купался сегодня!")
                else:
                    gd["last_pool_claim"] = today; gd["pool_buffs"] = 5; save_global_progress(gd)
                    print("⛲ Ты искупался! +20 атаки на 5 боев.")
                    
        elif choice == "14":
            if not gd.get("training_room_built"):
                if player.gold >= 2500: player.gold -= 2500; gd["training_room_built"] = True; save_global_progress(gd); print("🏋️ Тренировочный зал построен!")
                else: print("❌ Мало золота!")
            else:
                today = datetime.date.today().isoformat()
                if gd.get("last_training_claim") == today: print("❌ Ты уже тренировался сегодня!")
                else:
                    gd["last_training_claim"] = today; player.gain_exp(100); save_global_progress(gd)
                    print("🏋️ Ты потренировался и получил +100 опыта!")
                    
        elif choice == "15":
            if not gd.get("hermit_built"):
                if player.gold >= 3000: player.gold -= 3000; gd["hermit_built"] = True; save_global_progress(gd); print("🏚️ Хижина отшельника построена!")
                else: print("❌ Мало золота!")
            else:
                today = datetime.date.today().isoformat()
                if gd.get("last_hermit_claim") == today: print("❌ Отшельник уже помог тебе сегодня!")
                else:
                    gd["last_hermit_claim"] = today; player.debuffs = {}; save_global_progress(gd)
                    print("🏚️ Отшельник снял с тебя все дебаффы!")
                    
        elif choice == "16":
            if not gd.get("magic_tower_built"):
                if player.gold >= 7000: 
                    player.gold -= 7000; gd["magic_tower_built"] = True; player.max_mana += 20; player.mana += 20; save_global_progress(gd)
                    print("🗼 Магическая башня построена! +20 к максимальной мане.")
                else: print("❌ Мало золота!")
            else: print("🗼 Магическая башня уже построена.")
            
        elif choice == "17":
            if gd.get("mine_built") and gd.get("mine_lvl", 1) < 3:
                if player.gold >= 2000: player.gold -= 2000; gd["mine_lvl"] = gd.get("mine_lvl", 1) + 1; save_global_progress(gd); print(f"⛏️ Рудник улучшен до Ур.{gd['mine_lvl']}!")
                else: print("❌ Мало золота!")
                
        elif choice == "18":
            if gd.get("farm_built") and gd.get("farm_lvl", 1) < 3:
                if player.gold >= 2500: player.gold -= 2500; gd["farm_lvl"] = gd.get("farm_lvl", 1) + 1; save_global_progress(gd); print(f"🌾 Ферма улучшена до Ур.{gd['farm_lvl']}!")
                else: print("❌ Мало золота!")
                
        elif choice == "19":
            if gd.get("fountain_built") and gd.get("fountain_lvl", 1) < 2:
                if player.gold >= 3000: player.gold -= 3000; gd["fountain_lvl"] = 2; save_global_progress(gd); print("⛲ Фонтан улучшен! Теперь дает +10 атаки.")
                else: print("❌ Мало золота!")
                
        elif choice == "20":
            if gd.get("armory_built") and gd.get("armory_lvl", 1) < 2:
                if player.gold >= 4000: player.gold -= 4000; gd["armory_lvl"] = 2; player.defense += 10; save_global_progress(gd); print("🛡️ Оружейная улучшена! +10 защиты.")
                else: print("❌ Мало золота!")

    player.inventory_limit = original_limit
    # --- БОЕВКА ---
def battle(player, enemy, location_name):
    """Обёртка: временные баффы (Режим Бога, Бассейн) снимаются всегда, даже при побеге.
    Возвращает: "win" | "fled" | "dead"."""
    god = player.god_mode_battles > 0
    base = None
    if god:
        player.god_mode_battles -= 1
        base = (player.attack, player.defense, player.max_hp)
        player.attack *= 10; player.defense *= 10; player.max_hp *= 10; player.hp = player.max_hp
        print("🌟 РЕЖИМ БОГА: Твои статы увеличены в 10 раз на этот бой!")

    pool_gd = load_global_progress()
    pool = pool_gd.get("pool_buffs", 0) > 0
    if pool:
        pool_gd["pool_buffs"] -= 1
        save_global_progress(pool_gd)
        player.attack += 20
        print(f"⛲ Бафф Бассейна: +20 атаки (после этого боя останется: {pool_gd['pool_buffs']}).")

    try:
        return _battle(player, enemy, location_name)
    finally:
        if pool:
            player.attack -= 20
        if god:
            ratio = player.hp / player.max_hp if player.max_hp > 0 else 0
            # прирост за бой (например, от уровня) сохраняется, множитель x10 снимается
            player.attack = base[0] + (player.attack - base[0] * 10)
            player.defense = base[1] + (player.defense - base[1] * 10)
            player.max_hp = base[2] + (player.max_hp - base[2] * 10)
            if player.hp > 0:
                player.hp = max(1, int(ratio * player.max_hp))


def _battle(player, enemy, location_name):
    gd = load_global_progress()
    if location_name == "🌲 Лес" and gd.get("walls_built"):
        player.damage_reduction = 0.2
        print("🏗️ Ты сражаешься рядом с базой — стены снижают урон врагов на 20%!")
    else:
        player.damage_reduction = 0.0

    if gd.get("training_built") and location_name == "🌲 Лес": print("🏹 Стрельбище: +10% урона!")
    if gd.get("library_built"): print("📚 Библиотека: +20% опыта!")


    print(f"\n⚔️ В локации {location_name} на тебя напал {enemy.name}!")
    if player.char_class in ["Маг", "Некромант", "Повелитель Времени"] and player.mana < 15: player.mana = min(player.max_mana, player.mana + 20)
    
    if player.char_class == "Некромант" and player.skeleton_hp <= 0:
        player.skeleton_hp = 50
        print("💀 Ты призвал Скелета-помощника! (HP: 50)")

    def _try_revive():
        if not player.is_alive() and player.inventory.get("Свиток Воскрешения", 0) > 0:
            player.inventory["Свиток Воскрешения"] -= 1
            player.hp = player.max_hp // 2
            player.debuffs = {}
            print("\n📜 СВИТОК ВОСКРЕШЕНИЯ СРАБОТАЛ! Ты воскрес с 50% HP и продолжаешь бой!")
            return True
        return False

    skip_round_start = False  # True, если прошлый ввод не потратил ход (ошибка ввода, "нет предмета" и т.п.)
    while enemy.is_alive() and (player.is_alive() or _try_revive()):
        if not skip_round_start:
            if enemy.name == "Дракон" and player.paladin_hit_count % 3 == 0 and random.random() < 0.5:
                print("\n🐉 Дракон дышит огнем!")
                player.take_damage(30)
                player.debuffs["поджог"] = {"dmg": 10, "turns": 2}
                print("Ты загорелся! (10 урона в ход, 2 хода)")
                player.paladin_hit_count += 1
            elif enemy.name == "Финальный Босс" and random.random() < 0.3:
                print("\n👑 Финальный Босс призывает Стражников!")
                enemy.attack += 5
                print("Атака босса увеличена!")
            elif enemy.name == "Древний Ужас" and player.gold > 0:
                steal = min(player.gold, max(1, int(player.gold * 0.1)))
                player.gold -= steal
                enemy.hp = min(enemy.max_hp, enemy.hp + steal)
                print(f"\n👹 Древний Ужас крадет {steal} золота и лечится на эту сумму!")

            player.process_debuffs(); enemy.process_debuffs()
            if not player.is_alive() or not enemy.is_alive(): continue

            if player.char_class == "Некромант" and player.skeleton_hp > 0:
                print("💀 Твой Скелет атакует врага!")
                enemy.take_damage(10)
                if not enemy.is_alive(): continue
                player.skeleton_hp -= random.randint(10, 20)
                if player.skeleton_hp <= 0:
                    print("💥 Скелет разваливается, но взрывается костями! Враг получает 20 урона.")
                    enemy.take_damage(20)
                    if not enemy.is_alive(): continue

            if player.char_class == "Берсерк":
                player.hp -= 5
                print(f"(Берсерк: ты теряешь 5 HP каждый ход. HP: {player.hp})")
                if not player.is_alive(): continue
        skip_round_start = False

        print("\n1. Обычная атака")
        if player.char_class == "Воин": print("2. Мощный удар (10 HP, x2)")
        elif player.char_class == "Маг": print("2. Огненный шар (15 маны, x2.5)")
        elif player.char_class == "Разбойник": print("2. Удар в спину (30% крит x3)")
        elif player.char_class == "Танк": print("2. Глухая оборона (-70% урона)")
        elif player.char_class == "Паладин": print("2. Святое лечение (лечит 30 HP)")
        elif player.char_class == "Некромант": print("2. Похищение жизни (15 маны, урон + лечение)")
        elif player.char_class == "Берсерк": print("2. Кровавая ярость (x3 урона, но -10 HP)")
        elif player.char_class == "Ассасин": print("2. Удар милосердия (20% шанс убить мгновенно)")
        elif player.char_class == "Повелитель Времени": print("2. Откат времени (15 маны, сбрасывает ход врага)")

        if HALLOWEEN_MODE: print("6. 🎃 Сладость или Гадость (50/50)")
        if CHRISTMAS_MODE: print("6. 🎄 Подарить подарок (50 золота)")
        if SEPTEMBER_MODE: print("6. 📚 Сделать домашку (шанс 50% на -10 к атаке врага)")
        if is_birthday(gd): print("6. 🎂 Задуть свечи (шанс 50% на +10 HP)")
            
        print("7. Использовать 'Линукс'")
        print("8. Использовать 'Конфету'")
        print("9. Выпить Воду (20 HP и 20 маны)")
        print("10. 🔥 УЛЬТА (Требует 100 ярости)")
        print("11. Зелье маны (+30 маны)")
        print("3. Зелье")
        print("4. Свиток")
        print("5. Побег")
        choice = input("Твой выбор: ")

        if choice == "1":
            dmg = random.randint(player.attack - 3, player.attack + 3)
            if location_name == "🌲 Лес" and gd.get("training_built"): dmg = int(dmg * 1.1)
            if player.char_class == "Паладин":
                player.paladin_hit_count += 1
                if player.paladin_hit_count % 3 == 0:
                    print("✨ (Пассивка Паладина) СВЯТОЙ УДАР! Игнорирует защиту врага!")
                    enemy.hp -= dmg
                    print(f"{enemy.name} получает {dmg} чистого урона. (HP: {enemy.hp}/{enemy.max_hp})")
                else:
                    enemy.take_damage(dmg)
            else:
                enemy.take_damage(dmg)
                
            player.rage = min(100, player.rage + 20)
            print(f"🔥 Ярость: {player.rage}/100")
                
            if player.char_class == "Воин": player.hp -= 2; print(f"(Берсерк: -2 HP. HP: {player.hp})")
            if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            
        elif choice == "2":
            if player.char_class == "Воин":
                if player.hp > 10:
                    player.hp -= 10; enemy.take_damage(random.randint(player.attack, player.attack + 3) * 2)
                    player.hp -= 2; print(f"(Берсерк: -2 HP. HP: {player.hp})")
                    if enemy.is_alive() and random.random() < 0.3: enemy.add_debuff("кровотечение", 5, 3)
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
                else: print("Мало HP!"); skip_round_start = True
            elif player.char_class == "Маг":
                if player.mana >= 15:
                    player.mana -= 15; enemy.take_damage(int(random.randint(player.attack, player.attack + 3) * 2.5))
                    if enemy.is_alive() and random.random() < 0.5: enemy.add_debuff("горение", 8, 2)
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
                else: print("Мало маны!"); skip_round_start = True
            elif player.char_class == "Разбойник":
                if random.random() < 0.3: enemy.take_damage(random.randint(player.attack, player.attack + 3) * 3)
                else: enemy.take_damage(random.randint(player.attack - 3, player.attack + 3))
                if enemy.is_alive() and random.random() < 0.4: enemy.defense = max(0, enemy.defense - 2); print("Защита врага снижена!")
                if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            elif player.char_class == "Танк":
                player.is_blocking = True; print("Блок!")
                if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            elif player.char_class == "Паладин":
                player.heal(30)
                if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            elif player.char_class == "Некромант":
                if player.mana >= 15:
                    player.mana -= 15
                    dmg = random.randint(player.attack, player.attack + 3)
                    enemy.take_damage(dmg)
                    player.heal(dmg)
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
                else: print("Мало маны!"); skip_round_start = True
            elif player.char_class == "Берсерк":
                player.hp -= 10
                print("КРОВАВАЯ ЯРОСТЬ!")
                enemy.take_damage(random.randint(player.attack, player.attack + 3) * 3)
                if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            elif player.char_class == "Ассасин":
                if random.random() < 0.2:
                    print("💀 УДАР МИЛОСЕРДИЯ! Враг мгновенно убит!")
                    enemy.hp = 0
                else:
                    print("Промах...")
                    enemy.take_damage(random.randint(player.attack - 3, player.attack + 3))
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            elif player.char_class == "Повелитель Времени":
                if player.mana >= 15:
                    player.mana -= 15
                    print("⏳ Ты разрываешь нить времени! Враг откатывается назад, пропуская ход.")
                    continue
                else:
                    print("Мало маны!"); skip_round_start = True
        elif choice == "6":
            if HALLOWEEN_MODE:
                roll = random.random()
                if roll < 0.5:
                    enemy.take_damage(30); print("🍬 Сладость! Враг получает 30 урона.")
                else:
                    player.take_damage(10); enemy.add_debuff("страх", 0, 1); print("😱 Гадость! Ты теряешь 10 HP, но враг напуган и пропускает ход.")
            elif CHRISTMAS_MODE:
                if player.gold >= 50:
                    player.gold -= 50
                    if random.random() < 0.3:
                        print("🎄 Враг растроган подарком и уходит!")
                        enemy.hp = 0
                    else:
                        print("🎄 Враг злится! Он бьет сильнее.")
                        enemy.attack += 5
                        if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
                else: print("❌ Мало золота!"); skip_round_start = True
            elif SEPTEMBER_MODE:
                if random.random() < 0.5:
                    print("📚 Ты сделал домашку! Враг в шоке, его атака снижена.")
                    enemy.attack = max(1, enemy.attack - 10)
                else:
                    print("📚 Ты не сделал домашку... Враг бьет сильнее!")
                    player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            elif is_birthday(gd):
                if random.random() < 0.5:
                    player.heal(10); print("🎂 Ты задул свечи! +10 HP.")
                else:
                    print("🎂 Свечи не задулись... Враг смеется.")
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            else: skip_round_start = True
        elif choice == "7":
            if player.inventory.get("Линукс", 0) > 0:
                player.inventory["Линукс"] -= 1
                print("🐧 Линукс атакует! Враг мгновенно уничтожен!")
                enemy.hp = 0
            else:
                print("❌ У тебя нет 'Линукса'!"); skip_round_start = True
        elif choice == "8":
            if player.inventory.get("Конфета", 0) > 0:
                player.inventory["Конфета"] -= 1
                player.hp = player.max_hp
                print("🍬 Ты съел конфету и восстановил ВСЁ здоровье!")
            else:
                print("❌ У тебя нет 'Конфеты'!"); skip_round_start = True
        elif choice == "9":
            if player.inventory.get("Вода", 0) > 0:
                player.inventory["Вода"] -= 1
                player.heal(20)
                player.restore_mana(20)
                print("💧 Ты выпил Воду и восстановил силы!")
            else:
                print("❌ У тебя нет Воды!"); skip_round_start = True
        elif choice == "10":
            if player.rage >= 100:
                player.rage = 0
                ult_dmg = player.attack * 5
                print(f"🔥 ТЫ АКТИВИРУЕШЬ УЛЬТУ! Нанесено {ult_dmg} чистого урона!")
                enemy.hp -= ult_dmg
                print(f"{enemy.name} получает {ult_dmg} урона. (HP: {enemy.hp}/{enemy.max_hp})")
                if enemy.is_alive(): 
                    player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
            else:
                print("❌ Недостаточно ярости! Нужно 100."); skip_round_start = True
        elif choice == "11":
            if player.char_class not in ["Маг", "Некромант", "Повелитель Времени"]:
                print("❌ Твоему классу мана не нужна!"); skip_round_start = True
            elif player.inventory.get("Зелье маны", 0) > 0:
                player.inventory["Зелье маны"] -= 1
                player.restore_mana(30)
            else:
                print("❌ У тебя нет Зелья маны!"); skip_round_start = True
        elif choice == "3":
            if player.char_class == "Танк": print("❌ Танк не пьет зелья!"); skip_round_start = True; continue
            if player.inventory.get("Зелье лечения", 0) > 0:
                player.inventory["Зелье лечения"] -= 1
                heal_amt = 30
                if gd.get("hospital_built"): heal_amt += 20
                player.heal(heal_amt)
                if player.char_class in ["Маг", "Некромант", "Повелитель Времени"]: player.restore_mana(10)
                update_quest_progress(player, "potion")
            else: print("Нет зелий!"); skip_round_start = True
        elif choice == "4":
            print("\nДоступные свитки:")
            print(f"1. Свиток Огня ({player.inventory.get('Свиток Огня', 0)}) - 50 урона")
            print(f"2. Свиток Молнии ({player.inventory.get('Свиток Молнии', 0)}) - 60 урона")
            print(f"3. Свиток Воскрешения ({player.inventory.get('Свиток Воскрешения', 0)}) - Авто-спасение")
            print(f"4. Свиток Телепорта ({player.inventory.get('Свиток Телепорта', 0)}) - Мгновенный побег")
            print("0. Отмена")
            sc = input("Выбор: ")
            if sc == "1":
                if player.inventory.get("Свиток Огня", 0) > 0:
                    player.inventory["Свиток Огня"] -= 1
                    enemy.take_damage(50) 
                    print("📜 Ты прочитал Свиток Огня! Враг получает 50 урона!")
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
                else: print("Нет Свитков Огня!"); skip_round_start = True
            elif sc == "2":
                if player.inventory.get("Свиток Молнии", 0) > 0:
                    player.inventory["Свиток Молнии"] -= 1
                    enemy.take_damage(60)
                    print("📜 Ты прочитал Свиток Молнии! Враг получает 60 урона!")
                    if enemy.is_alive(): player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
                else: print("Нет Свитков Молнии!"); skip_round_start = True
            elif sc == "3":
                print("Свиток Воскрешения срабатывает автоматически при смерти."); skip_round_start = True
            elif sc == "4":
                if player.inventory.get("Свиток Телепорта", 0) > 0:
                    player.inventory["Свиток Телепорта"] -= 1
                    print("📜 Ты телепортируешься из боя!")
                    player.damage_reduction = 0.0
                    return "fled"
                else: print("Нет Свитков Телепорта!"); skip_round_start = True
            else: skip_round_start = True
        elif choice == "5":
            if random.random() < 0.5:
                print("Сбежал!")
                player.damage_reduction = 0.0
                return "fled"
            else: print("Не сбежал!"); player.take_damage(random.randint(enemy.attack - 2, enemy.attack + 2))
        else: print("Неверный ввод."); skip_round_start = True

    if not player.is_alive():
        _try_revive()  # одновременная смерть с врагом

    player.damage_reduction = 0.0

    if player.is_alive():
        print(f"\n✅ Победа над {enemy.name}!")
        gold_reward = int(enemy.gold_reward * 1.5) if player.mega_hard else enemy.gold_reward
        if player.nightmare: gold_reward *= 5
        exp_amount = enemy.exp_reward
        if gd.get("library_built"): exp_amount = int(exp_amount * 1.2)
        player.gain_exp(exp_amount); player.gold += gold_reward
        for res, amt in enemy.drops.items(): player.resources[res] = player.resources.get(res, 0) + amt; print(f"Ресурс: +{amt} {res}")
        
        if HALLOWEEN_MODE:
            candy_drop = random.randint(1, 3)
            gd = load_global_progress()
            gd["candies"] = gd.get("candies", 0) + candy_drop
            save_global_progress(gd)
            print(f"🎃 Ты нашел {candy_drop} конфет(ы)!")
            if random.random() < 0.2:
                player.inventory["Конфета"] = player.inventory.get("Конфета", 0) + 1
                print("🍬 Враг выронил Конфету (восстанавливает всё HP)!")
        elif CHRISTMAS_MODE:
            snow_drop = random.randint(1, 3)
            gd = load_global_progress()
            gd["snowflakes"] = gd.get("snowflakes", 0) + snow_drop
            save_global_progress(gd)
            print(f"❄️ Ты нашел {snow_drop} снежинок!")
        elif EASTER_MODE:
            egg_drop = random.randint(1, 3)
            gd = load_global_progress()
            gd["eggs"] = gd.get("eggs", 0) + egg_drop
            save_global_progress(gd)
            print(f"🐣 Ты нашел {egg_drop} пасхальных яиц!")
        elif SEPTEMBER_MODE:
            five_drop = random.randint(1, 3)
            gd = load_global_progress()
            gd["fives"] = gd.get("fives", 0) + five_drop
            save_global_progress(gd)
            print(f"📚 Ты получил {five_drop} пятерок!")
        elif is_birthday(gd):
            candle_drop = random.randint(1, 3)
            gd = load_global_progress()
            gd["candles"] = gd.get("candles", 0) + candle_drop
            save_global_progress(gd)
            print(f"🎂 Ты нашел {candle_drop} свечей!")
            
        if enemy.is_final_boss:
            print("\n🏆 ТЫ ПРОШЕЛ ИГРУ! Коды разблокированы! Башня открыта!")
            gd = load_global_progress(); gd["game_completed"] = True
            if player.hardcore: gd["nightmare_unlocked"] = True; print("🔥 ОТКРЫТ РЕЖИМ КОШМАР!")
            save_global_progress(gd)
        update_quest_progress(player, "kill")
        if enemy.is_final_boss or "Босс" in enemy.name or "Страж" in enemy.name or "Владыка" in enemy.name:
            update_quest_progress(player, "boss")
        return "win"
    else:
        print("\n💀 Ты погиб...")
        if player.hardcore:
            print("🔥 ХАРДКОР: Сохранение УДАЛЕНО!")
            if os.path.exists(HARDCORE_SAVE):
                try: os.remove(HARDCORE_SAVE)
                except Exception: pass
        else:
            lost = player.gold // 5
            player.gold -= lost
            player.hp = player.max_hp
            player.debuffs = {}
            print(f"🏥 Тебя вытащили с поля боя. Потеряно золота: {lost}. HP восстановлено.")
        return "dead"

# --- МАГАЗИН ---
def shop(player):
    print("\n🏪 Магазин")
    while True:
        gd = load_global_progress()
        currency_str = f"Золото: {player.gold} | 💎 Алмазы: {player.crystals}"
        if HALLOWEEN_MODE: currency_str += f" | 🎃 Конфеты: {gd.get('candies', 0)}"
        elif CHRISTMAS_MODE: currency_str += f" | ❄️ Снежинки: {gd.get('snowflakes', 0)}"
        elif EASTER_MODE: currency_str += f" | 🐣 Яйца: {gd.get('eggs', 0)}"
        elif SEPTEMBER_MODE: currency_str += f" | 📚 Пятерки: {gd.get('fives', 0)}"
        if is_birthday(gd): currency_str += f" | 🎂 Свечи: {gd.get('candles', 0)}"
        
        print(f"\n{currency_str}")
        print("1. Зелье HP (30)\n2. Зелье MP (50)")
        print("3. Стальной меч (+10 атк, 200)\n4. Секира (+20 атк, 500)\n5. Клинок Судьбы (+35 атк, 1500)")
        print("6. Кожаная куртка (+5 защ, 150)\n7. Кольчуга (+15 защ, 300)\n8. Мифриловая броня (+25 защ, 800)")
        print("9. Амулет HP (+30 HP, 200)")
        print("10. 📦 Сундук (100)")
        print("11. 📜 Свиток Огня (150)\n12. 📜 Свиток Молнии (300)\n13. 📜 Свиток Воскрешения (500)")
        print("14. 📜 Свиток Телепорта (100)")
        print("15. 💎 Купить Алмаз (500)")
        print("17. 💧 Вода (20 золота, восстанавливает 20 HP и 20 маны)")
        print("18. 🎒 Сумка для ресурсов (100 золота, навсегда освобождает место)")
        print("16. Выйти")
        choice = input("Выбор: ")

        if choice == "1":
            if not check_inventory_limit(player): continue
            if player.gold >= 30: player.gold -= 30; player.inventory["Зелье лечения"] = player.inventory.get("Зелье лечения", 0) + 1; print("Куплено!"); update_quest_progress(player, "spend", 30)
            else: print("Мало золота!")
        elif choice == "2":
            if not check_inventory_limit(player): continue
            if player.gold >= 50: player.gold -= 50; player.inventory["Зелье маны"] = player.inventory.get("Зелье маны", 0) + 1; print("Куплено!"); update_quest_progress(player, "spend", 50)
            else: print("Мало золота!")
        elif choice in SHOP_WEAPONS:
            name, price, bonus = SHOP_WEAPONS[choice]
            if name in player.owned_items: print("Уже куплено!")
            elif player.gold >= price:
                best_owned = max([b for (n, p, b) in SHOP_WEAPONS.values() if n in player.owned_items], default=0)
                player.gold -= price; player.attack += bonus; player.owned_items.append(name)
                if bonus > best_owned: player.weapon = name
                print("Куплено!"); update_quest_progress(player, "spend", price)
            else: print("Мало золота!")
        elif choice in SHOP_ARMORS:
            name, price = SHOP_ARMORS[choice]
            if ARMOR_DEF.get(player.armor, 0) >= ARMOR_DEF[name]: print("Уже есть броня не хуже!")
            elif player.gold >= price:
                player.gold -= price; player.armor = name
                print("Куплено!"); update_quest_progress(player, "spend", price)
            else: print("Мало золота!")
        elif choice == "9":
            if player.accessory == "Амулет здоровья": print("Уже есть!")
            elif player.gold >= 200: player.gold -= 200; player.accessory = "Амулет здоровья"; player.max_hp += 30; player.hp += 30; print("Куплено!"); update_quest_progress(player, "spend", 200)
            else: print("Мало золота!")
        elif choice == "10":
            if player.gold >= 100: player.gold -= 100; open_chest(player); update_quest_progress(player, "spend", 100)
            else: print("Мало золота! Нужно 100.")
        elif choice == "11":
            if not check_inventory_limit(player): continue
            if player.gold >= 150: player.gold -= 150; player.inventory["Свиток Огня"] = player.inventory.get("Свиток Огня", 0) + 1; print("Куплен Свиток Огня!"); update_quest_progress(player, "spend", 150)
            else: print("Мало золота!")
        elif choice == "12":
            if not check_inventory_limit(player): continue
            if player.gold >= 300: player.gold -= 300; player.inventory["Свиток Молнии"] = player.inventory.get("Свиток Молнии", 0) + 1; print("Куплен Свиток Молнии!"); update_quest_progress(player, "spend", 300)
            else: print("Мало золота!")
        elif choice == "13":
            if not check_inventory_limit(player): continue
            if player.gold >= 500: player.gold -= 500; player.inventory["Свиток Воскрешения"] = player.inventory.get("Свиток Воскрешения", 0) + 1; print("Куплен Свиток Воскрешения!"); update_quest_progress(player, "spend", 500)
            else: print("Мало золота!")
        elif choice == "14":
            if not check_inventory_limit(player): continue
            if player.gold >= 100: player.gold -= 100; player.inventory["Свиток Телепорта"] = player.inventory.get("Свиток Телепорта", 0) + 1; print("Куплен Свиток Телепорта!"); update_quest_progress(player, "spend", 100)
            else: print("Мало золота!")
        elif choice == "15":
            if player.gold >= 500: player.gold -= 500; player.crystals += 1; print("Куплен 1 Алмаз!"); update_quest_progress(player, "spend", 500)
            else: print("Мало золота!")
        elif choice == "16": break
        elif choice == "17":
            if not check_inventory_limit(player): continue
            if player.gold >= 20: 
                player.gold -= 20; player.inventory["Вода"] = player.inventory.get("Вода", 0) + 1; print("Куплена Вода!"); update_quest_progress(player, "spend", 20)
            else: print("Мало золота!")
        elif choice == "18":
            if player.has_bag:
                print("❌ У тебя уже есть сумка!")
            elif player.gold >= 100:
                player.gold -= 100
                player.has_bag = True
                print("✅ Ты купил Сумку! Теперь ресурсы не занимают место в инвентаре.")
                update_quest_progress(player, "spend", 100)
            else:
                print("❌ Мало золота!")
                # --- АРЕНА ---
def arena(player):
    print("\n🗡️ КРОВАВАЯ АРЕНА")
    if player.arena_level > 0: print(f"Рекорд: Волна {player.arena_level}")
    while True:
        wave = player.arena_level + 1
        enemy = Enemy(f"Волна {wave}", hp=50 * wave, attack=10 * wave, defense=2 * wave, exp_reward=50 * wave, gold_reward=30 * wave, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
        win = battle(player, enemy, "Кровавая арена")
        if win == "win": player.arena_level = wave; print(f"🎉 Волна {wave} пройдена!"); update_quest_progress(player, "arena")
        elif win == "fled": print("Ты сбежал с арены."); break
        else: print("Ты пал..."); break
        if input("Продолжить? (y/n): ").lower() != 'y': break

# --- НОВЫЕ РЕЖИМЫ ---
def colosseum(player):
    print("\n🏛️ КОЛИЗЕЙ (3 врага подряд)")
    print("Сразись с 3 врагами без отдыха. Победа = уникальный сундук.")
    if input("Начать? (y/n): ").lower() != 'y': return
    
    for i in range(1, 4):
        enemy = Enemy(f"Гладиатор {i}", hp=100 * i, attack=15 * i, defense=5 * i, exp_reward=100 * i, gold_reward=50 * i, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
        win = battle(player, enemy, f"Колизей (Враг {i})")
        if win != "win":
            print("Ты пал на арене..." if win == "dead" else "Ты сбежал с арены..."); return
    print("🎉 Ты прошел Колизей! Награда: сундук!")
    open_chest(player)

def dungeon(player):
    print("\n🕳️ ПОДЗЕМЕЛЬЕ (Roguelike)")
    print("Каждый заход — новая карта. В конце — босс.")
    if input("Войти? (y/n): ").lower() != 'y': return
    
    rooms = random.randint(3, 5)
    print(f"Ты входишь в подземелье. Комнат: {rooms}")
    
    for i in range(rooms):
        print(f"\n=== Комната {i+1} ===")
        if random.random() < 0.3:
            print("Ты нашел сундук!")
            open_chest(player)
        else:
            enemy = Enemy("Страж подземелья", hp=80 + i*20, attack=12 + i*3, defense=4 + i*2, exp_reward=50 + i*20, gold_reward=30 + i*15, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
            win = battle(player, enemy, f"Комната {i+1}")
            if win != "win": return
            
    print("\n=== БОСС ПОДЗЕМЕЛЬЯ ===")
    boss = Enemy("Владыка Подземелья", hp=500, attack=50, defense=20, exp_reward=500, gold_reward=300, is_final_boss=False, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
    win = battle(player, boss, "Босс Подземелья")
    if win == "win":
        print("🎉 Ты прошел подземелье!")
        player.attack += 10
        print("Ты получил +10 к атаке навсегда!")

# --- ЛОКАЦИИ ---
# --- ЛАВКА СТАРЬЁВЩИКА ---
RESOURCE_PRICES = {
    "Шкура": 8, "Зуб": 10, "Кость": 8, "Плоть": 6, "Яд": 15, "Песок": 5, "Лед": 12,
    "Камень": 25, "Огонь": 40, "Чернила": 50, "Чешуя": 60, "Перо": 70,
    "Свет": 120, "Тьма": 130, "Душа": 150, "Золото": 20, "Трофей": 800, "Абсолют": 3000,
    "Снежинка": 15, "Яйцо": 15, "Пятерка": 15, "Конфета": 20, "Свеча": 15,
}
KEEP_FROM_BULK_SALE = {"Чешуя"}  # нужна для Кузницы — «продать всё» её не трогает

def _hot_item():
    """Товар дня: один и тот же для всех в течение суток, цена x2."""
    rnd = random.Random("hot:" + datetime.date.today().isoformat())
    return rnd.choice(sorted(RESOURCE_PRICES))

def _market_price(name):
    """Цена за штуку: базовая ±, плавает по дням, у товара дня x2."""
    base = RESOURCE_PRICES.get(name, 10)
    rnd = random.Random(f"{datetime.date.today().isoformat()}:{name}")
    price = int(base * rnd.uniform(0.8, 1.3))
    if name == _hot_item(): price *= 2
    return max(1, price)

def _sell_resource(player, name, amount):
    have = player.resources.get(name, 0)
    amount = min(amount, have)
    if amount <= 0: return 0
    total = _market_price(name) * amount
    player.resources[name] = have - amount
    if player.resources[name] <= 0: del player.resources[name]
    player.gold += total
    return total

def junk_shop(player):
    print("\n" + "="*40)
    print("🧺 ЛАВКА СТАРЬЁВЩИКА")
    print("«Всё, что не прибито, куплю. Что прибито, куплю дешевле.»")
    print("="*40)
    while True:
        items = sorted((n, a) for n, a in player.resources.items() if a > 0)
        if not items:
            print("\nУ тебя нет ресурсов для продажи. Иди добывай!")
            return
        hot = _hot_item()
        print(f"\n💰 Золото: {player.gold} | 🔥 Товар дня: {hot} (цена x2, цены меняются каждый день)")
        for i, (n, a) in enumerate(items, 1):
            note = " 🔥" if n == hot else (" (нужна для Кузницы)" if n == "Чешуя" else "")
            print(f"{i}. {n} x{a} — {_market_price(n)} зол./шт.{note}")
        print("A. Продать всё (кроме Чешуи)\n0. Выйти")
        choice = input("Выбор: ").strip().lower()

        if choice == "0":
            return
        if choice in ("a", "а"):
            sellable = [(n, a) for n, a in items if n not in KEEP_FROM_BULK_SALE]
            if not sellable:
                print("❌ Нечего продавать (Чешую я не трогаю)."); continue
            total = sum(_market_price(n) * a for n, a in sellable)
            if input(f"Продать всё за {total} золота? (y/n): ").strip().lower() != "y":
                continue
            got = sum(_sell_resource(player, n, a) for n, a in sellable)
            print(f"✅ Продано всё лишнее: +{got} золота!")
        elif choice.isdigit() and 1 <= int(choice) <= len(items):
            name, have = items[int(choice) - 1]
            raw = input(f"Сколько {name} продать? (число или 'все', у тебя {have}): ").strip().lower()
            amt = have if raw in ("все", "всё", "all") else (int(raw) if raw.isdigit() else 0)
            if amt <= 0 or amt > have:
                print("❌ Неверное количество!"); continue
            total = _market_price(name) * amt
            if total >= 500 and input(f"Точно продать {amt} {name} за {total} золота? (y/n): ").strip().lower() != "y":
                continue
            got = _sell_resource(player, name, amt)
            print(f"✅ Продано {amt} {name}: +{got} золота!")
        else:
            print("❌ Неверный выбор.")

# --- БОСС-РАШ ---
BOSS_RUSH_ORDER = ["Дракон", "Голем", "Кракен", "Ангел", "Пожиратель", "Финальный Босс", "Древний Ужас"]

def _boss_factory(name):
    for loc in LOCATIONS.values():
        for factory in loc["enemies"]:
            if getattr(factory, "enemy_name", None) == name:
                return factory
    return None

def boss_rush(player):
    gd = load_global_progress()
    if not gd.get("game_completed"):
        print("\n🔒 Босс-раш открывается после победы над Финальным Боссом.")
        return
    total = len(BOSS_RUSH_ORDER)
    print("\n" + "="*40)
    print("👹 БОСС-РАШ")
    print("="*40)
    print(f"{total} боссов подряд. Между боями восстанавливается лишь 20% HP и маны.")
    print("После каждого босса можно забрать награду и уйти. Погибнешь — награды не будет.")
    print("Награда: 1 💎 и 250 золота за каждого побеждённого босса. Полная зачистка: +5 💎 и сундук.")
    if player.boss_rush_best > 0: print(f"🏆 Твой рекорд: {player.boss_rush_best}/{total} боссов")
    if input("Начать? (y/n): ").lower() != "y": return

    defeated = 0
    outcome = "cashout"
    for i, boss_name in enumerate(BOSS_RUSH_ORDER, 1):
        factory = _boss_factory(boss_name)
        if factory is None: continue
        boss = factory(player)
        boss.is_final_boss = False  # чтобы бой не засчитал «прохождение игры» повторно
        print(f"\n=== БОСС {i}/{total}: {boss.name} ===")
        result = battle(player, boss, f"Босс-раш ({i}/{total})")
        if result == "dead":
            outcome = "dead"; break
        if result == "fled":
            outcome = "fled"; break
        defeated += 1
        if i == total:
            outcome = "clear"; break
        player.hp = min(player.max_hp, player.hp + player.max_hp // 5)
        player.mana = min(player.max_mana, player.mana + player.max_mana // 5)
        print(f"\n✅ Босс повержен! ({defeated}/{total}) Передышка: HP {player.hp}/{player.max_hp}")
        if input("Идти дальше? (y/n): ").lower() != "y":
            outcome = "cashout"; break

    if defeated > player.boss_rush_best:
        player.boss_rush_best = defeated
        print(f"🏆 Новый рекорд: {defeated}/{total}!")
    if outcome == "dead":
        print("💀 Босс-раш провален. Награды нет.")
        return
    if outcome == "fled":
        print("🏃 Ты сбежал, но то, что заработал, остаётся.")
    gold = 250 * defeated
    player.gold += gold; player.crystals += defeated
    print(f"🎁 Награда: +{gold} золота, +{defeated} 💎")
    if outcome == "clear":
        player.crystals += 5
        print("👑 ПОЛНАЯ ЗАЧИСТКА! Бонус: +5 💎, сундук и 🌟 Осколок бесконечности!")
        open_chest(player)
        gd = load_global_progress(); gd["infinity_shards"] = gd.get("infinity_shards", 0) + 1; save_global_progress(gd)

def locations_menu(player):
    while True:
        print("\n" + "="*30); print("🗺️ КАРТА"); print("="*30)
        keys = sorted(LOCATIONS.keys(), key=lambda x: int(x))
        for i, key in enumerate(keys, 1):
            loc = LOCATIONS[key]
            is_completed = loc["name"] in player.completed_locations
            is_unlocked = True
            if loc["required_location"] and loc["required_location"] not in player.completed_locations: is_unlocked = False
            
            gd = load_global_progress()
            if loc["name"] == "👹 Секретный босс" and not gd.get("secret_boss_unlocked", False):
                print(f"{i}. {loc['name']} 🔒 (Нужен код)")
                continue

            if is_completed: status = "✅ (Пройдено)"
            elif is_unlocked: status = "➡️ (Доступно)"
            else: status = f"🔒 (Нужно: {loc['required_location']})"
            print(f"{i}. {loc['name']} {status}")
        print("0. Назад")
        choice = input("\nВыбери: ")
        if choice == "0": break
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(keys):
                loc = LOCATIONS[keys[index]]
                if loc["required_location"] and loc["required_location"] not in player.completed_locations: print("❌ Заблокировано!"); continue
                
                gd = load_global_progress()
                if loc["name"] == "👹 Секретный босс" and not gd.get("secret_boss_unlocked", False):
                    print("❌ Секретный босс заблокирован! Введи код 'secret_boss'."); continue

                enemy_factory = random.choice(loc["enemies"])
                enemy = enemy_factory(player)
                
                if CHRISTMAS_MODE and loc["name"] == "🌲 Лес" and random.random() < 0.1:
                    print("\n🎄 ИЗ СУГРОБА ПОЯВЛЯЕТСЯ СНЕГОВИК-БОСС! 🎄")
                    enemy = Enemy("Снеговик-Босс", hp=150, attack=25, defense=5, exp_reward=200, gold_reward=150, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
                    enemy.drops = {"Снежинка": 5}
                elif HALLOWEEN_MODE and loc["name"] == "🌲 Лес" and random.random() < 0.1:
                    print("\n🎃 ИЗ ТЬМЫ ПОЯВЛЯЕТСЯ ДЖЕК-ФОНАРЬ! 🎃")
                    enemy = Enemy("Джек-Фонарь", hp=150, attack=25, defense=5, exp_reward=200, gold_reward=150, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
                    enemy.drops = {"Конфета": 5}
                elif EASTER_MODE and loc["name"] == "🌲 Лес" and random.random() < 0.1:
                    print("\n🐣 ИЗ ТРАВЫ ПОЯВЛЯЕТСЯ ГИГАНТСКОЕ ЯЙЦО! 🐣")
                    enemy = Enemy("Гигантское Яйцо", hp=150, attack=25, defense=5, exp_reward=200, gold_reward=150, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
                    enemy.drops = {"Яйцо": 5}
                elif SEPTEMBER_MODE and loc["name"] == "🌲 Лес" and random.random() < 0.1:
                    print("\n📚 ИЗ КУСТОВ ПОЯВЛЯЕТСЯ ДИРЕКТОР ШКОЛЫ! 📚")
                    enemy = Enemy("Директор", hp=150, attack=25, defense=5, exp_reward=200, gold_reward=150, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
                    enemy.drops = {"Пятерка": 5}
                elif is_birthday(gd) and loc["name"] == "🌲 Лес" and random.random() < 0.1:
                    print("\n🎂 ИЗ НИОТКУДА ПОЯВЛЯЕТСЯ ГИГАНТСКИЙ ТОРТ! 🎂")
                    enemy = Enemy("Гигантский Торт", hp=150, attack=25, defense=5, exp_reward=200, gold_reward=150, hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
                    enemy.drops = {"Свеча": 5}
                    
                win = battle(player, enemy, loc['name'])
                if not player.is_alive(): break  # герой погиб (хардкор)
                if win == "win" and loc["name"] not in player.completed_locations:
                    player.completed_locations.append(loc["name"])
                    print(f"🎉 Локация {loc['name']} пройдена!")
                    update_quest_progress(player, "loc")
                    save_game(player)

# --- КОДЫ ---
def enter_code(player):
    global MUSOR_MODE
    gd = load_global_progress()
    code = input("\nКод: ").strip()
    if code in player.used_codes: print("❌ Использован!"); return

    if code == "mihailz73 is here": player.gold += 30; print("✅ +30 золота")
    elif code == "super_sword": player.attack += 10; player.weapon = "Легендарный меч"; print("✅ +10 атаки")
    elif code == "hp_boost": player.gold += 100; print("✅ +100 золота")
    elif code == "heal_me_plz": player.inventory["Зелье лечения"] = player.inventory.get("Зелье лечения", 0) + 5; print("✅ +5 зелий")
    elif code == "tank_lover": player.max_hp += 50; player.hp += 50; print("✅ +50 HP")
    elif code == "rich_boy": player.gold += 500; print("✅ +500 золота")
    elif code == "god_mode": player.completed_locations = ["🌲 Лес", "🕷️ Пещера", "🏰 Замок", "🌋 Вулкан", "🌊 Подводный город", "☁️ Небесная крепость", "🌑 Бездна", "👑 Тронный зал"]; print("✅ Все локации открыты!")
    elif code == "exp_farm": player.gain_exp(500); print("✅ +500 опыта")
    elif code == "secret_boss":
        gd["secret_boss_unlocked"] = True
        save_global_progress(gd)
        print("✅ Секретный босс открыт на карте!")
    elif code == "sans":
        player.sans_mode = True
        player.max_hp = 1
        player.hp = 1
        print("💀 РЕЖИМ САНСА АКТИВИРОВАН! У тебя 1 HP, но враги не могут тебя ударить.")
    elif code == "vip_shop":
        gd["vip_unlocked"] = True
        save_global_progress(gd)
        print("💎 VIP-МАГАЗИН ОТКРЫТ! (Проверь главное меню)")
    elif code == "musor_drop":
        MUSOR_MODE = True
        print("🗑️ РЕЖИМ 'МУСОРНЫЙ ДРОП' АКТИВИРОВАН! ВСЕ СЛОВА ТЕПЕРЬ - MUSOR DROP!")
    elif code == "halloween" and HALLOWEEN_MODE:
        gd["candies"] = gd.get("candies", 0) + 20
        save_global_progress(gd)
        print("🎃 +20 конфет! С Хэллоуином!")
    elif code == "xmas" and CHRISTMAS_MODE:
        gd["snowflakes"] = gd.get("snowflakes", 0) + 20
        save_global_progress(gd)
        print("❄️ +20 снежинок! С Рождеством!")
    elif code == "easter" and EASTER_MODE:
        gd["eggs"] = gd.get("eggs", 0) + 20
        save_global_progress(gd)
        print("🐣 +20 пасхальных яиц! С Пасхой!")
    elif code == "september" and SEPTEMBER_MODE:
        gd["fives"] = gd.get("fives", 0) + 20
        save_global_progress(gd)
        print("📚 +20 пятерок! С 1 Сентября!")
    elif code == "birthday" and is_birthday(gd):
        gd["candles"] = gd.get("candles", 0) + 20
        save_global_progress(gd)
        print("🎂 +20 свечей! С Днем Рождения!")
    elif code == "chilzhirchik_idet_po_vashu_dushu":
        player.inventory["Конфета"] = player.inventory.get("Конфета", 0) + 1
        print("🍬 Ты получил 'Конфету' (восстанавливает всё HP)!")
    elif code == "ya_programist...ya-drochy-na-linux":
        player.inventory["Линукс"] = player.inventory.get("Линукс", 0) + 3
        print("🐧 Ты получил 'Линукс' x3 (мгновенно побеждает врага)!")
    elif code == "=D":
        player.gold += 15; print("✅ +15 золота")
    elif code == ">:)":
        player.gold += 15; print("✅ +15 золота")
    elif code == "globus":
        player.gold += 50; print("✅ +50 золота")
        if SEPTEMBER_MODE:
            gd["fives"] = gd.get("fives", 0) + 15
            save_global_progress(gd)
            print("📚 Бонус 1 Сентября: +15 пятерок!")
    elif code == "ascii":
        print("  ___  _____")
        print(" /   ||  ___|")
        print("| |  || |___ ")
        print("| |_ ||___  |")
        print("\\___/|_____/")
    else: print("❌ Неверный код."); return
    player.used_codes.append(code)

# --- КАЗИНО ---
def casino(player):
    print("\n🎰 КАЗИНО")
    while True:
        print(f"\nТвоё золото: {player.gold} | 💎 Алмазы: {player.crystals} | ❤️ HP: {player.hp}/{player.max_hp}")
        print("1. Рулетка (Ставка 100 золота: Красное/Чёрное x2, Зеро x36)")
        print("2. 🩸 Рулетка Крови (Ставка 500 золота: 50% - выигрыш 1000, 40% - проигрыш, 10% - боль и алмаз)")
        print("0. Выйти из казино")
        
        choice = input("Твой выбор: ")
        
        if choice == "0":
            print("Ты покидаешь казино.")
            return
            
        elif choice == "1":
            if player.gold < 100:
                print("❌ У тебя меньше 100 золота!")
                continue
            print("На что ставишь? 1. Красное (x2)  2. Чёрное (x2)  3. Зеро (x36)")
            bet = input("Ставка: ").strip()
            if bet not in ("1", "2", "3"):
                print("❌ Неверная ставка.")
                continue
            player.gold -= 100
            pocket = random.randint(0, 36)
            if pocket == 0: result = "3"; result_name = "ЗЕРО"
            elif pocket % 2 == 1: result = "1"; result_name = "красное"
            else: result = "2"; result_name = "чёрное"
            if bet == result:
                win = 100 * (36 if result == "3" else 2)
                player.gold += win
                print(f"🎯 Выпало {result_name}! Ты выиграл {win} золота!")
            else:
                print(f"🔴 Выпало {result_name}. Ты проиграл 100 золота.")
            save_game(player)

        elif choice == "2":
            if player.gold < 500:
                print("❌ Для Рулетки Крови нужно 500 золота!")
                continue
            if player.hp <= 100:
                print("❌ У тебя слишком мало HP для Рулетки Крови! (Нужно больше 100)")
                continue
                
            player.gold -= 500
            roll = random.random()
            
            if roll < 0.50:
                player.gold += 1000
                print("🟢 Ты выиграл 1000 золота! (x2)")
            elif roll < 0.90:
                print("🔴 Ты проиграл 500 золота. Не повезло...")
            else:
                dmg = 100
                player.hp -= dmg
                player.crystals += 1
                print(f"🩸 КРОВАВАЯ ПЛАТА! Ты потерял {dmg} HP, но получил 💎 1 Алмаз!")
                if not player.is_alive():
                    print("💀 Ты истек кровью прямо за столом...")
                    if player.hardcore:
                        if os.path.exists(HARDCORE_SAVE): os.remove(HARDCORE_SAVE)
                    return
            save_game(player)
        else:
            print("❌ Неверный ввод.")

# --- ОБЩЕЕ ---
def _has_space(player, n=1):
    """Есть ли в рюкзаке место под n предметов (ресурсы занимают место, если нет сумки)."""
    total = sum(player.inventory.values()) + (0 if player.has_bag else sum(player.resources.values()))
    if total + n > player.inventory_limit:
        print(f"❌ Не хватит места в инвентаре! ({total}/{player.inventory_limit}, нужно ещё {n})")
        return False
    return True

# --- РАБОЧИЕ ЛАГЕРЯ ---
WORKER_MAX_LEVEL = 10
WORKER_MAX_DAYS = 3   # дольше трёх дней рабочие добычу не копят
# роль: (название, цена найма, [(ресурс, с какого уровня, базовое количество в день)])
WORKERS = {
    "miner": ("⛏️ Шахтёр", 600, [("Камень", 1, 2), ("Песок", 1, 2), ("Лед", 3, 1), ("Огонь", 5, 1)]),
    "farmer": ("🌾 Фермер", 600, [("Плоть", 1, 2), ("Яд", 1, 1), ("Перо", 4, 1)]),
    "hunter": ("🏹 Охотник", 800, [("Шкура", 1, 2), ("Зуб", 1, 2), ("Кость", 2, 2), ("Чешуя", 4, 1)]),
}

def _worker_daily(role, lvl):
    """Что рабочий приносит за день на этом уровне: новые ресурсы открываются с уровнем, количество растёт."""
    return {name: base + (lvl - min_lvl) // 2 for name, min_lvl, base in WORKERS[role][2] if lvl >= min_lvl}

def _worker_xp_needed(lvl):
    return 3 * lvl   # дней работы до следующего уровня

def workers_collect(gd):
    """Рабочие сдают добычу на склад лагеря за прошедшие дни (не больше WORKER_MAX_DAYS).
    Меняет gd (но не сохраняет его) и возвращает строки отчёта."""
    report = []
    today = datetime.date.today()
    for role, w in gd.get("workers", {}).items():
        if role not in WORKERS: continue
        w.setdefault("lvl", 1); w.setdefault("xp", 0)
        try: last = datetime.date.fromisoformat(w.get("last_work") or "")
        except ValueError: last = today
        days = min(WORKER_MAX_DAYS, max(0, (today - last).days))   # если часы перевели назад — просто 0
        w["last_work"] = today.isoformat()
        if days == 0: continue
        storage = gd.setdefault("camp_resources", {})
        got = []
        for name, amt in _worker_daily(role, w["lvl"]).items():
            storage[name] = storage.get(name, 0) + amt * days
            got.append(f"{name} x{amt * days}")
        w["xp"] += days
        levels = 0
        while w["lvl"] < WORKER_MAX_LEVEL and w["xp"] >= _worker_xp_needed(w["lvl"]):
            w["xp"] -= _worker_xp_needed(w["lvl"]); w["lvl"] += 1; levels += 1
        up = f" 🎉 Новый уровень: {w['lvl']}!" if levels else ""
        report.append(f"{WORKERS[role][0]} принёс на склад: {', '.join(got)}.{up}")
    return report

def workers_menu(player):
    print("\n👷 РАБОЧИЕ ЛАГЕРЯ")
    print("Нанятые рабочие раз в день сдают ресурсы на склад лагеря (копят до 3 дней) и растут в уровне.")
    while True:
        gd = load_global_progress()
        gd.setdefault("workers", {})
        report = workers_collect(gd)
        if report:
            save_global_progress(gd)
            for line in report: print("📦 " + line)
        print(f"\n💰 Золото: {player.gold}")
        roles = list(WORKERS)
        for i, role in enumerate(roles, 1):
            title, price, _ = WORKERS[role]
            w = gd["workers"].get(role)
            if w:
                daily = ", ".join(f"{n} x{a}" for n, a in _worker_daily(role, w["lvl"]).items())
                nxt = f"тренировка {250 * w['lvl']} золота" if w["lvl"] < WORKER_MAX_LEVEL else "МАКС. УРОВЕНЬ"
                print(f"{i}. {title} — ур. {w['lvl']}/{WORKER_MAX_LEVEL}, опыт {w['xp']}/{_worker_xp_needed(w['lvl'])} | в день: {daily} | {nxt}")
            else:
                print(f"{i}. {title} — не нанят. Найм: {price} золота")
        print("0. Назад")
        choice = input("Выбор: ").strip()
        if choice == "0": return
        if not (choice.isdigit() and 1 <= int(choice) <= len(roles)):
            print("❌ Неверный выбор."); continue
        role = roles[int(choice) - 1]
        title, price, _ = WORKERS[role]
        w = gd["workers"].get(role)
        if w is None:
            if player.gold < price:
                print("❌ Не хватает золота!"); continue
            player.gold -= price
            gd["workers"][role] = {"lvl": 1, "xp": 0, "last_work": datetime.date.today().isoformat()}
            save_global_progress(gd)
            print(f"✅ {title} нанят! Первая добыча будет завтра.")
        elif w["lvl"] >= WORKER_MAX_LEVEL:
            print("✅ Рабочий уже на максимальном уровне!")
        else:
            cost = 250 * w["lvl"]
            if player.gold < cost:
                print("❌ Не хватает золота на тренировку!"); continue
            player.gold -= cost
            w["lvl"] += 1
            save_global_progress(gd)
            print(f"💪 {title} потренировался и вырос до уровня {w['lvl']}!")

# --- КРАФТ ---
CRAFT_RECIPES = [
    ("Зелье лечения", {"Кость": 2, "Яд": 1}),
    ("Зелье маны", {"Лед": 2, "Песок": 1}),
    ("Свиток Огня", {"Чешуя": 1, "Огонь": 1}),
    ("Свиток Молнии", {"Камень": 2, "Перо": 1}),
    ("Свиток Телепорта", {"Свет": 1, "Песок": 2}),
    ("Свиток Воскрешения", {"Душа": 1, "Свет": 1, "Тьма": 1}),
]

def craft_menu(player):
    print("\n⚗️ КРАФТ")
    while True:
        have = ", ".join(f"{n} x{a}" for n, a in sorted(player.resources.items()) if a > 0) or "пусто"
        print(f"\nРесурсы: {have}")
        for i, (item, cost) in enumerate(CRAFT_RECIPES, 1):
            print(f"{i}. {item} — " + ", ".join(f"{n} x{a}" for n, a in cost.items()))
        print("0. Назад")
        choice = input("Что крафтим? ").strip()
        if choice == "0": return
        if not (choice.isdigit() and 1 <= int(choice) <= len(CRAFT_RECIPES)):
            print("❌ Неверный выбор."); continue
        item, cost = CRAFT_RECIPES[int(choice) - 1]
        raw = input("Сколько? (число, Enter = 1): ").strip()
        count = 1 if raw == "" else (int(raw) if raw.isdigit() else 0)
        if count <= 0:
            print("❌ Неверное количество."); continue
        made = 0
        for _ in range(count):
            if any(player.resources.get(n, 0) < a for n, a in cost.items()):
                print("❌ Не хватает ресурсов!"); break
            # крафт освобождает место (3 ресурса -> 1 предмет), блокируем только если место реально не хватает
            total = sum(player.inventory.values()) + (0 if player.has_bag else sum(player.resources.values()))
            delta = 1 - (0 if player.has_bag else sum(cost.values()))
            if delta > 0 and total + delta > player.inventory_limit:
                print(f"❌ Инвентарь полон! ({total}/{player.inventory_limit})"); break
            for n, a in cost.items():
                player.resources[n] -= a
                if player.resources[n] <= 0: del player.resources[n]
            player.inventory[item] = player.inventory.get(item, 0) + 1
            made += 1
        if made:
            print(f"✅ Скрафчено: {item} x{made}")
            update_quest_progress(player, "craft", made)

# --- ДЕРЕВО АПГРЕЙДОВ ---
UPGRADES = {
    "hp": ("❤️ Здоровье", "+10 макс. HP"),
    "attack": ("⚔️ Сила", "+2 атаки"),
    "defense": ("🛡️ Стойкость", "+1 защиты"),
    "mana": ("🔮 Мана", "+5 макс. маны"),
}
UPGRADE_MAX = 10

def upgrade_tree(player):
    print("\n🌳 ДЕРЕВО АПГРЕЙДОВ (навсегда, за 💎; уровень N стоит N 💎)")
    while True:
        keys = [k for k in UPGRADES if k != "mana" or player.max_mana > 0]
        print(f"\n💎 Алмазы: {player.crystals}")
        for i, k in enumerate(keys, 1):
            lvl = player.upgrades.get(k, 0)
            name, desc = UPGRADES[k]
            price = f"{lvl + 1} 💎" if lvl < UPGRADE_MAX else "МАКС"
            print(f"{i}. {name} (ур. {lvl}/{UPGRADE_MAX}) — {desc} | след.: {price}")
        print("0. Назад")
        choice = input("Выбор: ").strip()
        if choice == "0": return
        if not (choice.isdigit() and 1 <= int(choice) <= len(keys)):
            print("❌ Неверный выбор."); continue
        k = keys[int(choice) - 1]
        lvl = player.upgrades.get(k, 0)
        if lvl >= UPGRADE_MAX:
            print("✅ Уже максимум!"); continue
        cost = lvl + 1
        if player.crystals < cost:
            print("❌ Не хватает алмазов!"); continue
        player.crystals -= cost
        player.upgrades[k] = lvl + 1
        if k == "hp": player.max_hp += 10; player.hp += 10
        elif k == "attack": player.attack += 2
        elif k == "defense": player.defense += 1
        elif k == "mana": player.max_mana += 5; player.mana += 5
        print(f"✅ {UPGRADES[k][0]} улучшено до ур. {lvl + 1}!")

# --- ЕЖЕДНЕВНЫЕ КВЕСТЫ ---
DAILY_QUEST_POOL = [
    {"name": "Победить 8 врагов", "type": "kill", "target": 8, "gold": 120, "crystals": 0},
    {"name": "Выпить 3 зелья", "type": "potion", "target": 3, "gold": 80, "crystals": 0},
    {"name": "Потратить 300 золота", "type": "spend", "target": 300, "gold": 100, "crystals": 0},
    {"name": "Пройти 2 волны на арене", "type": "arena", "target": 2, "gold": 150, "crystals": 0},
    {"name": "Скрафтить 2 предмета", "type": "craft", "target": 2, "gold": 100, "crystals": 1},
    {"name": "Победить 1 босса", "type": "boss", "target": 1, "gold": 200, "crystals": 1},
]

def check_daily_quests(player):
    gd = load_global_progress()
    today = datetime.date.today().isoformat()
    quests = gd.get("quests")
    if gd.get("last_quest_date") != today or not isinstance(quests, list) or not quests:
        gd["last_quest_date"] = today
        gd["quests"] = [dict(q, progress=0, done=False) for q in random.sample(DAILY_QUEST_POOL, 3)]
        gd["quests_bonus_paid"] = False
        print("\n🌅 Новый день, новые задания!")
    print("\n📜 ЕЖЕДНЕВНЫЕ ЗАДАНИЯ")
    for q in gd["quests"]:
        if not q["done"] and q["progress"] >= q["target"]:
            q["done"] = True
            player.gold += q["gold"]; player.crystals += q["crystals"]
            extra = f", +{q['crystals']} 💎" if q["crystals"] else ""
            print(f"🎁 Выполнено: {q['name']}! +{q['gold']} золота{extra}")
        state = "✅" if q["done"] else f"{min(q['progress'], q['target'])}/{q['target']}"
        print(f"- {q['name']} [{state}]")
    if all(q["done"] for q in gd["quests"]) and not gd.get("quests_bonus_paid"):
        gd["quests_bonus_paid"] = True
        player.crystals += 1
        print("🏆 Все задания дня выполнены! Бонус: +1 💎")
    save_global_progress(gd)

# --- КОЛЕСО ФОРТУНЫ ---
def fortune_wheel(player):
    gd = load_global_progress()
    today = datetime.date.today().isoformat()
    if gd.get("last_spin") == today:
        print("\n🎡 Сегодня ты уже крутил колесо. Приходи завтра!")
        return
    gd["last_spin"] = today
    prizes = [("gold", 30), ("potion", 20), ("mana", 12), ("scroll", 12), ("resource", 10),
              ("crystal", 8), ("jackpot", 3), ("shard", 1), ("nothing", 4)]
    kind = random.choices([k for k, _ in prizes], weights=[w for _, w in prizes])[0]
    print("\n🎡 Колесо крутится...")
    if kind == "gold":
        g = random.randint(50, 250); player.gold += g; print(f"💰 Выпало {g} золота!")
    elif kind in ("potion", "mana", "scroll", "resource"):
        if not _has_space(player, 2):
            player.gold += 50; print("💰 Места нет, колесо выдало 50 золота вместо приза.")
        elif kind == "potion":
            player.inventory["Зелье лечения"] = player.inventory.get("Зелье лечения", 0) + 2; print("🧪 Выпало 2 Зелья лечения!")
        elif kind == "mana":
            player.inventory["Зелье маны"] = player.inventory.get("Зелье маны", 0) + 1; print("🔮 Выпало Зелье маны!")
        elif kind == "scroll":
            s = random.choice(["Свиток Огня", "Свиток Молнии"])
            player.inventory[s] = player.inventory.get(s, 0) + 1; print(f"📜 Выпал {s}!")
        else:
            r = random.choice(["Шкура", "Зуб", "Кость", "Огонь", "Яд", "Камень"]); n = random.randint(2, 4)
            player.resources[r] = player.resources.get(r, 0) + n; print(f"🪨 Выпало: {r} x{n}!")
    elif kind == "crystal":
        player.crystals += 1; print("💎 Выпал Алмаз!")
    elif kind == "jackpot":
        player.crystals += 5; player.gold += 500; print("🎰 ДЖЕКПОТ! +5 💎 и 500 золота!")
    elif kind == "shard":
        gd["infinity_shards"] = gd.get("infinity_shards", 0) + 1; print("🌟 НЕВЕРОЯТНО! Осколок бесконечности!")
    else:
        print("💨 Сегодня пусто. Повезёт завтра!")
    save_global_progress(gd)

# --- ЧЁРНЫЙ РЫНОК ---
BLACK_MARKET = [
    ("Свиток Воскрешения", 3, "Свиток Воскрешения", 1),
    ("Набор: Зелье лечения x5", 2, "Зелье лечения", 5),
    ("Свиток Телепорта x2", 2, "Свиток Телепорта", 2),
    ("🌟 Осколок бесконечности", 15, None, 1),
]

def black_market(player):
    print("\n🕶️ ЧЁРНЫЙ РЫНОК (платить только алмазами)")
    while True:
        print(f"\n💎 Алмазы: {player.crystals}")
        for i, (title, price, _, _) in enumerate(BLACK_MARKET, 1):
            print(f"{i}. {title} — {price} 💎")
        print("0. Назад")
        choice = input("Выбор: ").strip()
        if choice == "0": return
        if not (choice.isdigit() and 1 <= int(choice) <= len(BLACK_MARKET)):
            print("❌ Неверный выбор."); continue
        title, price, item, qty = BLACK_MARKET[int(choice) - 1]
        if player.crystals < price:
            print("❌ Не хватает алмазов!"); continue
        if item is None:
            gd = load_global_progress(); gd["infinity_shards"] = gd.get("infinity_shards", 0) + 1; save_global_progress(gd)
            player.crystals -= price
            print(f"🌟 Куплено! Осколков: {gd['infinity_shards']}/5 для Режима Бога.")
        elif _has_space(player, qty):
            player.crystals -= price
            player.inventory[item] = player.inventory.get(item, 0) + qty
            print(f"✅ Куплено: {title}")

# --- БАШНЯ ---
def tower_menu(player):
    gd = load_global_progress()
    if not gd.get("game_completed"):
        print("\n🔒 Башня открывается после победы над Финальным Боссом.")
        return
    start = (player.tower_floor // 5) * 5 + 1   # контрольная точка каждые 5 этажей
    print("\n🏰 БАШНЯ")
    print("Бесконечные этажи, каждый сложнее предыдущего. Каждый 5-й этаж — босс.")
    print("Новый рекорд: каждые 5 этажей +1 💎, каждые 10 этажей +1 🌟 Осколок бесконечности.")
    if player.tower_floor > 0: print(f"🏆 Рекорд: этаж {player.tower_floor}")
    if input(f"Начать с этажа {start}? (y/n): ").strip().lower() != "y": return
    floor = start
    while True:
        boss = floor % 5 == 0
        hp, atk, df = 80 + 30 * floor, 10 + 4 * floor, floor
        exp, gold = 40 + 15 * floor, 25 + 10 * floor
        if boss: hp *= 2; atk = int(atk * 1.5); exp *= 3; gold *= 3
        name = "Босс Башни" if boss else f"Обитатель этажа {floor}"
        enemy = Enemy(name, hp=hp, attack=atk, defense=df, exp_reward=exp, gold_reward=gold,
                      hardcore=player.hardcore, mega_hard=player.mega_hard, nightmare=player.nightmare)
        print(f"\n🏰 ЭТАЖ {floor}" + (" — БОСС!" if boss else ""))
        result = battle(player, enemy, f"Башня (этаж {floor})")
        if result != "win":
            print("💀 Башня тебя победила." if result == "dead" else "🏃 Ты спустился вниз.")
            return
        if floor > player.tower_floor:
            player.tower_floor = floor
            print(f"🏆 Новый рекорд башни: этаж {floor}!")
            if floor % 5 == 0:
                player.crystals += 1; print("💎 +1 Алмаз за этаж!")
            if floor % 10 == 0:
                g2 = load_global_progress(); g2["infinity_shards"] = g2.get("infinity_shards", 0) + 1
                save_global_progress(g2); print("🌟 +1 Осколок бесконечности!")
        player.hp = min(player.max_hp, player.hp + player.max_hp // 10)
        save_game(player)
        if input("Подняться выше? (y/n): ").strip().lower() != "y": return
        floor += 1

# --- VIP-МАГАЗИН ---
CURRENCY_NAMES = {"candies": "🎃 конфет", "snowflakes": "❄️ снежинок", "eggs": "🥚 яиц", "fives": "📚 пятёрок", "candles": "🕯️ свечей"}
VIP_ITEMS = [
    ("Тыквенный шлем (броня +50)", {"candies": 40}, "armor", "Тыквенный шлем"),
    ("Шапка Санты (броня +50)", {"snowflakes": 40}, "armor", "Шапка Санты"),
    ("Пасхальный набор: Свиток Воскрешения + 2 Зелья лечения", {"eggs": 30}, "easter", None),
    ("Отличник: +1000 опыта", {"fives": 30}, "exp", 1000),
    ("Праздничный торт: +20 макс. HP навсегда", {"candles": 30}, "cake", None),
    ("Конфета (восстанавливает всё HP)", {"candies": 10}, "candy", None),
    ("Броня Бога (броня +100)", {k: 60 for k in CURRENCY_NAMES}, "armor", "Броня Бога"),
]

def vip_shop(player):
    print("\n💎 VIP-МАГАЗИН (праздничная валюта)")
    while True:
        gd = load_global_progress()
        print("\nУ тебя: " + ", ".join(f"{gd.get(k, 0)} {n}" for k, n in CURRENCY_NAMES.items()))
        for i, (title, cost, _, _) in enumerate(VIP_ITEMS, 1):
            print(f"{i}. {title} — " + ", ".join(f"{a} {CURRENCY_NAMES[k]}" for k, a in cost.items()))
        print("0. Назад")
        choice = input("Выбор: ").strip()
        if choice == "0": return
        if not (choice.isdigit() and 1 <= int(choice) <= len(VIP_ITEMS)):
            print("❌ Неверный выбор."); continue
        title, cost, kind, arg = VIP_ITEMS[int(choice) - 1]
        if any(gd.get(k, 0) < a for k, a in cost.items()):
            print("❌ Не хватает праздничной валюты!"); continue
        if kind == "armor":
            if ARMOR_DEF.get(player.armor, 0) >= ARMOR_DEF[arg]:
                print("❌ У тебя уже есть броня не хуже!"); continue
            player.armor = arg
        elif kind == "easter":
            if not _has_space(player, 3): continue
            player.inventory["Свиток Воскрешения"] = player.inventory.get("Свиток Воскрешения", 0) + 1
            player.inventory["Зелье лечения"] = player.inventory.get("Зелье лечения", 0) + 2
        elif kind == "exp":
            player.gain_exp(arg)
        elif kind == "cake":
            player.max_hp += 20; player.hp = player.max_hp
        elif kind == "candy":
            if not _has_space(player, 1): continue
            player.inventory["Конфета"] = player.inventory.get("Конфета", 0) + 1
        for k, a in cost.items(): gd[k] = gd.get(k, 0) - a
        save_global_progress(gd)
        print(f"✅ Куплено: {title}")

# --- СУНДУК ---
# Простая версия (open_chest в присланном файле не было). Если есть своя — вставь её, она заменит эту.
if "open_chest" not in globals():
    def open_chest(player):
        roll = random.random()
        if roll < 0.6:
            g = random.randint(50, 200); player.gold += g
            print(f"📦 В сундуке {g} золота!")
        elif roll < 0.9:
            player.inventory["Зелье лечения"] = player.inventory.get("Зелье лечения", 0) + 1
            print("📦 В сундуке Зелье лечения!")
        else:
            player.crystals += 1
            print("📦 В сундуке 💎 Алмаз!")

# --- ЛОКАЦИИ ---
LOCATIONS = {
    "1": {"name": "🌲 Лес", "enemies": [
        make_enemy("Волк", 25, 6, 1, 15, 10, drops={"Шкура": 1}),
        make_enemy("Гоблин", 30, 8, 2, 20, 15, drops={"Зуб": 1}),
    ], "required_location": None},
    "2": {"name": "🕷️ Пещера", "enemies": [
        make_enemy("Паук", 50, 12, 4, 35, 25, drops={"Зуб": 2}),
        make_enemy("Скелет", 60, 14, 5, 40, 30, drops={"Кость": 1}),
    ], "required_location": "🌲 Лес"},
    "3": {"name": "🏰 Замок", "enemies": [
        make_enemy("Тёмный маг", 120, 25, 8, 100, 70, drops={"Чешуя": 1}),
        make_enemy("Дракон", 200, 35, 15, 250, 150, drops={"Чешуя": 3}),
    ], "required_location": "🕷️ Пещера"},
    "4": {"name": "🌋 Вулкан", "enemies": [
        make_enemy("Элементаль", 250, 40, 18, 300, 200, drops={"Огонь": 1}),
        make_enemy("Голем", 300, 45, 20, 400, 250, drops={"Камень": 2}),
    ], "required_location": "🏰 Замок"},
    "5": {"name": "🌊 Подводный город", "enemies": [
        make_enemy("Русалка", 450, 65, 28, 700, 600, drops={"Чешуя": 2}),
        make_enemy("Кракен", 600, 75, 30, 900, 800, drops={"Чернила": 1}),
    ], "required_location": "🌋 Вулкан"},
    "6": {"name": "☁️ Небесная крепость", "enemies": [
        make_enemy("Гарпия", 850, 95, 38, 1300, 1100, drops={"Перо": 3}),
        make_enemy("Ангел", 1000, 110, 40, 1600, 1300, drops={"Свет": 1}),
    ], "required_location": "🌊 Подводный город"},
    "7": {"name": "🌑 Бездна", "enemies": [
        make_enemy("Жрец", 1400, 140, 50, 2200, 1800, drops={"Тьма": 1}),
        make_enemy("Пожиратель", 1600, 160, 55, 2500, 2000, drops={"Душа": 2}),
    ], "required_location": "☁️ Небесная крепость"},
    "8": {"name": "👑 Тронный зал", "enemies": [
        make_enemy("Гвардия", 2500, 200, 70, 3500, 3000, drops={"Золото": 5}),
        make_enemy("Финальный Босс", 5000, 300, 100, 10000, 10000, is_final_boss=True, drops={"Трофей": 1}),
    ], "required_location": "🌑 Бездна"},
    "9": {"name": "👹 Секретный босс", "enemies": [
        make_enemy("Древний Ужас", 10000, 400, 150, 50000, 50000, drops={"Абсолют": 1}),
    ], "required_location": "👑 Тронный зал"},
    "10": {"name": "🏜️ Пустыня", "enemies": [
        make_enemy("Скорпион", 100, 20, 5, 60, 40, drops={"Яд": 1}),
        make_enemy("Песчаный червь", 300, 40, 10, 300, 200, drops={"Песок": 5}),
    ], "required_location": "🏰 Замок"},
    "11": {"name": "🧊 Ледяная пещера", "enemies": [
        make_enemy("Ледяной элементаль", 200, 30, 10, 150, 100, drops={"Лед": 2}),
        make_enemy("Снежный голем", 400, 50, 15, 400, 250, drops={"Лед": 5}),
    ], "required_location": "🏜️ Пустыня"},
    "12": {"name": "⚰️ Кладбище", "enemies": [
        make_enemy("Скелет-воин", 60, 15, 5, 40, 30, drops={"Кость": 2}),
        make_enemy("Зомби", 80, 20, 7, 50, 35, drops={"Плоть": 1}),
    ], "required_location": "🕷️ Пещера"},
    "13": {"name": "🏛️ Колизей", "enemies": [
        make_enemy("Гладиатор", 150, 25, 10, 100, 70, drops={}),
    ], "required_location": "🏰 Замок"},
}

# --- ГЛАВНЫЙ ЦИКЛ ---
def main():
    global MUSOR_MODE
    gd = load_global_progress()
    print("="*50)
    if CHRISTMAS_MODE:
        print("🎄 ТЕКСТОВАЯ RPG: MERRY CHRISTMAS EDITION 🎄")
    elif HALLOWEEN_MODE:
        print("🎃 ТЕКСТОВАЯ RPG: HALLOWEEN EDITION 🎃")
    elif EASTER_MODE:
        print("🐣 ТЕКСТОВАЯ RPG: EASTER EDITION 🐣")
    elif SEPTEMBER_MODE:
        print("📚 ТЕКСТОВАЯ RPG: BACK TO SCHOOL 📚")
    elif is_birthday(gd):
        print("🎂 ТЕКСТОВАЯ RPG: HAPPY BIRTHDAY! 🎂")
    else:
        print("ТЕКСТОВАЯ RPG: MEGA UPDATE (ЭНДГЕЙМ)")
    print("="*50)
    
    if gd.get("game_completed"): print("🔥 (Игра пройдена! Доступна Башня и коды в 'help')")
    if gd.get("birthday_postponed") and not is_any_holiday():
        print("🎂 Твой ДР был отложен из-за праздника! Празднуем сегодня! 🎂")
    
    while True:
        save_exists = os.path.exists(SAVE_FILE); hardcore_exists = os.path.exists(HARDCORE_SAVE)
        print("\n1. Новая игра\n2. Продолжить (Обычная)\n3. Новая игра (ХАРДКОР)\n4. Продолжить (ХАРДКОР)\n5. Выйти")
        if not gd.get("birthday"):
            print("6. Ввести дату рождения (для режима ДР)")
        else:
            print(f"6. Дата рождения: {gd['birthday']}")
        print("7. 🌐 Мультиплеер")
        choice = input("Выбор: ")
        
        if choice == "7":
            if multiplayer is None:
                print("\n❌ Файл multiplayer.py не найден рядом с игрой.")
            else:
                print("\n🌐 МУЛЬТИПЛЕЕР")
                print("1. 🤝 Команда — сражаться вместе и передавать ресурсы")
                print("2. ⚔️ PvP — друг против друга")
                print("0. Назад")
                mp_choice = input("Выбор: ")
                if mp_choice == "1":
                    multiplayer.multiplayer_menu("team")
                elif mp_choice == "2":
                    multiplayer.multiplayer_menu("pvp")
            continue

        if choice == "6":
            bday = input("Введи дату рождения (ДД.ММ): ")
            try:
                datetime.datetime.strptime(bday, "%d.%m")
                gd["birthday"] = bday
                save_global_progress(gd)
                print("✅ Дата рождения сохранена!")
            except Exception:
                print("❌ Неверный формат! Введи ДД.ММ (например, 15.05)")
            continue

        if choice in ["1", "3"]:
            is_hard = (choice == "3")
            if is_hard: print("\n🔥 РЕЖИМ ХАРДКОР: Враги x2 HP, +50% урона. Смерть = удаление сейва.")
            
            name = input("Имя: ")
            
            mega_hard = False
            if name.lower() == "далбаёб":
                mega_hard = True
                print("\n" + "!"*50)
                print("⚠️ АКТИВИРОВАН СЕКРЕТНЫЙ РЕЖИМ: МЕГА-ХАРДКОР! ⚠️")
                print("!"*50 + "\n")

            nightmare = False
            if gd.get("nightmare_unlocked"):
                n_choice = input("🔥 Доступен РЕЖИМ КОШМАР (Враги x2 урона, но дроп x5). Включить? (y/n): ").lower()
                if n_choice == 'y': nightmare = True
            
            print(f"\nОтлично, {name}. Теперь выбери свой путь (8 классов):")
            print("="*40)
            print("1. ВОИН (HP 150, Мощный удар, Кровотечение. Дебафф: Берсерк)")
            print("2. МАГ (HP 100, Огненный шар, Поджог. Дебафф: Стеклянная пушка)")
            print("3. РАЗБОЙНИК (HP 80, Криты x3, Снижение защиты. Дебафф: Хрупкость)")
            print("4. ТАНК (HP 250, Блок -70%. Дебафф: Нельзя пить зелья)")
            print("5. ПАЛАДИН (HP 180, Лечение в бою, Защита 12)")
            print("6. НЕКРОМАНТ (HP 90, Призыв скелета, Похищение жизни)")
            print("7. БЕРСЕРК (HP 120, Урон x3, но теряет HP каждый ход)")
            print("8. АССАСИН (HP 70, 20% шанс убить с одного удара)")
            print("9. ПОВЕЛИТЕЛЬ ВРЕМЕНИ (HP 110, Умеет откатывать ход назад)")
            print("="*40)

            while True:
                c = input("Выбери класс (1-9): ").strip()
                if c in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                    char_class = {"1":"Воин", "2":"Маг", "3":"Разбойник", "4":"Танк", "5":"Паладин", "6":"Некромант", "7":"Берсерк", "8":"Ассасин", "9":"Повелитель Времени"}[c]
                    break
                else:
                    print("❌ Неверный класс! Введи число от 1 до 9.")
            
            player = Player(name, char_class, hardcore=is_hard, mega_hard=mega_hard, nightmare=nightmare)
            
            if check_sudden_death(player, delete_save=False): continue
            
            print(f"\n{name}, ты вступаешь на путь {char_class}а. Удачи!")
            save_game(player); game_loop(player)
            
        elif choice == "2" and save_exists:
            player = load_game(hardcore=False)
            if player: game_loop(player)
        elif choice == "4" and hardcore_exists:
            player = load_game(hardcore=True)
            if player:
                if check_sudden_death(player): continue 
                game_loop(player)
        elif choice == "5": break

def game_loop(player):
    while player.is_alive():
        gd = load_global_progress()
        
        menu_str = "1. Бой\n2. Магазин\n3. Статы\n4. Карта\n5. Крафт\n6. Арена\n7. Код\n8. Сохранить\n9. В меню\n10. Help\n11. Дерево апгрейдов\n12. Квесты\n13. Колесо Фортуны\n14. Черный рынок\n15. Башня\n16. Колизей\n17. Подземелье\n18. Лагерь\n21. 🎰 Казино\n22. 👹 Босс-раш\n24. 🧺 Лавка старьёвщика\n25. 📱 Играть на телефоне (QR)"
        if gd.get("vip_unlocked"): menu_str += "\n19. 💎 VIP-Магазин"
        if gd.get("guild_points") is not None: menu_str += "\n20. 🏛️ Гильдия"
        if gd.get("infinity_shards", 0) >= 5: menu_str += "\n23. 🌟 Режим Бога (5 осколков)"
        
        if is_any_holiday() or is_birthday(gd):
            if not gd.get("vip_unlocked"):
                print("\n💡 ПОДСКАЗКА: Сейчас праздник! Введи код 'vip_shop' (пункт 7), чтобы открыть VIP-магазин и купить праздничные уникальные вещи за праздничную валюту! 🎁")
            else:
                print("\n💡 ПОДСКАЗКА: Загляни в VIP-магазин (пункт 19), там сейчас продаются праздничные уникальные вещи! 🎁")

        print(f"\n{menu_str}")
        choice = input("Выбор: ")

        if choice == "1":
            enemy = random.choice(LOCATIONS["1"]["enemies"])(player); battle(player, enemy, LOCATIONS["1"]["name"]); save_game(player)
        elif choice == "2": shop(player); save_game(player)
        elif choice == "3": player.show_stats()
        elif choice == "4": locations_menu(player)
        elif choice == "5": craft_menu(player); save_game(player)
        elif choice == "6": arena(player); save_game(player)
        elif choice == "7": enter_code(player); save_game(player)
        elif choice == "8": save_game(player)
        elif choice == "9": save_game(player); break
        elif choice == "10" or choice.lower() == "help":
            if load_global_progress().get("game_completed"):
                print("\nКОДЫ: mihailz73 is here, super_sword, hp_boost, heal_me_plz, tank_lover, rich_boy, god_mode, exp_farm, secret_boss, sans, vip_shop, musor_drop, halloween, xmas, easter, september, birthday, ascii, chilzhirchik_idet_po_vashu_dushu, ya_programist...ya-drochy-na-linux, =D, >:), globus")
            else: print("\n❌ Коды скрыты! Пройди игру, чтобы увидеть список.")
        elif choice == "11": upgrade_tree(player); save_game(player)
        elif choice == "12": check_daily_quests(player); save_game(player)
        elif choice == "13": fortune_wheel(player); save_game(player)
        elif choice == "14": black_market(player); save_game(player)
        elif choice == "15": tower_menu(player); save_game(player)
        elif choice == "16": colosseum(player); save_game(player)
        elif choice == "17": dungeon(player); save_game(player)
        elif choice == "18": camp_menu(player); save_game(player)
        elif choice == "19" and gd.get("vip_unlocked"):
            vip_shop(player); save_game(player)
        elif choice == "20":
            guild_menu(player); save_game(player)
        elif choice == "21":
            casino(player); save_game(player)
        elif choice == "22":
            boss_rush(player); save_game(player)
        elif choice == "24":
            junk_shop(player); save_game(player)
        elif choice == "25":
            if phone_server is None:
                print("\n❌ Файл phone_server.py не найден рядом с игрой.")
            else:
                save_game(player)
                phone_server.phone_menu(main)
        elif choice == "23" and gd.get("infinity_shards", 0) >= 5:
            gd["infinity_shards"] -= 5
            save_global_progress(gd)
            player.god_mode_battles = 1
            print("🌟 РЕЖИМ БОГА АКТИВИРОВАН НА 1 БОЙ! (Все статы x10)")

    if not player.is_alive():
        print("\n💀 Твой герой погиб. Возвращаемся в меню.")

if __name__ == "__main__":
    main()
