import datetime
import itertools
import logging
import typing as T
from dataclasses import dataclass

import urwid

from pqcli import random
from pqcli.config import *
from pqcli.lingo import *

logger = logging.getLogger(__name__)


class SignalMixin:
    def __init_subclass__(cls: T.Any, **kwargs: T.Any) -> None:
        urwid.signals.register_signal(cls, cls.signals)
        super().__init_subclass__(**kwargs)

    def emit(self, signal_name: str, *user_data: T.Any) -> None:
        urwid.signals.emit_signal(self, signal_name, *user_data)

    def connect(self, signal_name: str, callback: T.Callable) -> None:
        urwid.signals.connect_signal(self, signal_name, callback)


def level_up_time(level: int) -> int:
    # seconds
    return 20 * level * 60


class Bar(SignalMixin):
    signals = ["change"]

    def __init__(self, max_: int, position: float = 0.0) -> None:
        self.position = position
        self.max_ = max_
        self.emit("change")

    def reset(self, new_max: int, position: float = 0.0) -> None:
        self.max_ = new_max
        self.position = position
        self.emit("change")

    def increment(self, inc: float) -> None:
        self.reposition(self.position + inc)

    @property
    def done(self) -> bool:
        return self.position >= self.max_

    def reposition(self, new_pos: float) -> None:
        self.position = float(min(new_pos, self.max_))
        self.emit("change")


class Stats(SignalMixin):
    signals = ["change"]

    def __init__(self, values: T.Dict[StatType, int]) -> None:
        self.values = values

    def __iter__(self) -> T.Iterator[T.Tuple[StatType, int]]:
        return iter(self.values.items())

    def __getitem__(self, stat: StatType) -> int:
        return self.values[stat]

    def increment(self, stat: StatType, qty: int = 1) -> None:
        self.values[stat] += qty
        logger.info("Increased %s to %d", stat.value, self[stat])
        self.emit("change")


class QuestBook(SignalMixin):
    signals = ["complete_act", "complete_quest"]

    def __init__(self) -> None:
        self._quests: T.List[str] = []
        self.act = 0
        self.plot_bar = Bar(max_=26)
        self.quest_bar = Bar(max_=1)
        self.monster: T.Optional[Monster] = None

    @property
    def quests(self) -> T.List[str]:
        return self._quests

    @property
    def current_quest(self) -> T.Optional[str]:
        if self._quests:
            return self._quests[-1]
        return None

    def add_quest(self, name: str) -> None:
        logger.info("Commencing quest: %s", name)
        self._quests = self._quests[-100:]
        self._quests.append(name)


@dataclass
class InventoryItem:
    name: str
    quantity: int


class Inventory(SignalMixin):
    signals = ["gold_change", "item_add", "item_change", "item_del"]

    def __init__(self, capacity: int = 0) -> None:
        self._gold = 0
        self._items: T.List[InventoryItem] = []
        self.encum_bar = Bar(max_=capacity)

    @property
    def gold(self) -> int:
        return self._gold

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> T.Iterator[InventoryItem]:
        return iter(self._items)

    def __getitem__(self, idx: int) -> InventoryItem:
        return self._items[idx]

    def add_gold(self, quantity: int) -> None:
        logger.info(
            "%s %s",
            "Spent" if quantity < 0 else "Got paid",
            indefinite("gold piece", abs(quantity)),
        )
        self._gold += quantity
        self.emit("gold_change")

    def pop(self, index: int) -> None:
        item = self._items[index]
        logger.info("Lost %s (qty=%d)", item.name, item.quantity)
        self._items.pop(index)
        self.sync_encumbrance()
        self.emit("item_del", item)

    def add(self, item_name: str, quantity: int) -> None:
        logger.info("Gained %s", indefinite(item_name, quantity))
        for item in self._items:
            if item.name == item_name:
                item.quantity += quantity
                self.emit("item_change", item)
                break
        else:
            item = InventoryItem(name=item_name, quantity=quantity)
            self._items.append(item)
            self.emit("item_add", item)
        self.sync_encumbrance()

    def sync_encumbrance(self) -> None:
        self.encum_bar.reposition(sum(item.quantity for item in self._items))

    def set_capacity(self, capacity: int) -> None:
        self.encum_bar.reset(capacity, self.encum_bar.position)


class Equipment(SignalMixin):
    signals = ["change"]

    def __init__(self) -> None:
        self._items: T.Dict[EquipmentType, str] = {
            EquipmentType.weapon: "Sharp Rock",
            EquipmentType.hauberk: "-3 Burlap",
        }

    def __iter__(self) -> T.Iterator[T.Tuple[EquipmentType, str]]:
        return iter(self._items.items())

    def __getitem__(self, equipment_type: EquipmentType) -> T.Optional[str]:
        return self._items.get(equipment_type, None)

    def put(self, equipment_type: EquipmentType, item_name: str) -> None:
        self._items[equipment_type] = item_name
        self.emit("change", equipment_type, item_name)


@dataclass
class Spell:
    name: str
    level: int


class SpellBook(SignalMixin):
    signals = ["add", "change"]

    def __init__(self) -> None:
        self.spells: T.List[Spell] = []

    def __iter__(self) -> T.Iterator[Spell]:
        return iter(self.spells)

    def add(self, spell_name: str, level: int) -> None:
        for spell in self.spells:
            if spell.name == spell_name:
                spell.level += level
                logger.info("Learned %s at level %d", spell_name, spell.level)
                self.emit("change", spell)
                break
        else:
            spell = Spell(name=spell_name, level=level)
            self.spells.append(spell)
            logger.info("Learned %s at level %d", spell.name, spell.level)
            self.emit("add", spell)


@dataclass
class BaseTask:
    description: str
    duration: int


@dataclass
class KillTask(BaseTask):
    monster: T.Optional[Monster] = None


class BuyTask(BaseTask):
    pass


class HeadingToKillingFieldsTask(BaseTask):
    pass


class HeadingToMarketTask(BaseTask):
    pass


class SellTask(BaseTask):
    pass


class RegularTask(BaseTask):
    pass


class PlotTask(RegularTask):
    pass


class Player(SignalMixin):
    signals = ["new_task", "level_up"]

    def __init__(
        self,
        name: str,
        birthday: datetime.datetime,
        race: Race,
        class_: Class,
        stats: Stats,
    ) -> None:
        self.name: str = name
        self.birthday: datetime.datetime = birthday
        self.race: Race = race
        self.class_: Class = class_
        self.stats: Stats = stats

        self.exp_bar = Bar(max_=level_up_time(1))
        self.level = 1

        self.quest_book = QuestBook()
        self.inventory = Inventory(capacity=10 + self.stats[StatType.strength])
        self.equipment = Equipment()
        self.spell_book = SpellBook()

        self.task_bar = Bar(max_=0)
        self.task: T.Optional[BaseTask] = None
        self.queue: T.List[BaseTask] = [
            RegularTask(
                "Experiencing an enigmatic and foreboding night vision", 10_000
            ),
            RegularTask(
                "Much is revealed about that wise old bastard "
                "you'd underestimated",
                6_000,
            ),
            RegularTask(
                "A shocking series of events leaves you "
                "alone and bewildered, but resolute",
                6_000,
            ),
            RegularTask(
                "Drawing upon an unrealized reserve of determination, "
                "you set out on a long and dangerous journey",
                4_000,
            ),
            PlotTask(f"Loading {act_name(self.quest_book.act + 1)}", 2_000),
        ]

        self.set_task(RegularTask("Loading", 2_000))

    def set_task(self, task: BaseTask) -> None:
        self.task = task
        self.task_bar.reset(task.duration)
        logger.info("%s...", task.description)
        self.emit("new_task")

    def equip_price(self) -> int:
        return 5 * (self.level ** 2) + 10 * self.level + 20

    def level_up(self) -> None:
        self.level += 1
        logger.info("Leveled up to level %d!", self.level)
        self.stats.increment(
            StatType.hp_max,
            self.stats[StatType.condition] // 3 + 1 + random.below(4),
        )
        self.stats.increment(
            StatType.mp_max,
            self.stats[StatType.intelligence] // 3 + 1 + random.below(4),
        )
        self.win_stat()
        self.win_stat()
        self.win_spell()
        self.exp_bar.reset(level_up_time(self.level))
        self.emit("level_up")

    def win_stat(self) -> bool:
        chosen_stat: T.Optional[StatType] = None

        if random.odds(1, 2):
            chosen_stat = random.choice(list(StatType))
        else:
            # favor the best stat so it will tend to clump
            t = sum(value ** 2 for _stat, value in self.stats)
            t = random.below(t)
            chosen_stat = None
            for stat, value in self.stats:
                chosen_stat = stat
                t -= value ** 2
                if t < 0:
                    break

        assert chosen_stat is not None
        self.stats.increment(chosen_stat)
        if chosen_stat == StatType.strength:
            self.inventory.set_capacity(10 + self.stats[StatType.strength])
        return True

    def win_spell(self) -> None:
        self.spell_book.add(
            SPELLS[
                random.below_low(
                    min(self.stats[StatType.wisdom] + self.level, len(SPELLS))
                )
            ],
            1,
        )

    def win_equipment(self) -> None:
        choice = random.choice(list(EquipmentType))

        stuff: T.List[EquipmentPreset]
        better: T.List[Modifier]
        worse: T.List[Modifier]

        if choice == EquipmentType.weapon:
            stuff = WEAPONS
            better = OFFENSE_ATTRIB
            worse = OFFENSE_BAD
        else:
            stuff = SHIELDS if choice == EquipmentType.shield else ARMORS
            better = DEFENSE_ATTRIB
            worse = DEFENSE_BAD

        equipment = pick_equipment(stuff, self.level)
        name = equipment.name
        plus = self.level - equipment.quality
        if plus < 0:
            modifier_pool = worse
        else:
            modifier_pool = better
        count = 0
        while count < 2 and plus:
            modifier = random.choice(modifier_pool)
            if modifier.name in name:
                break  # no repeats
            if abs(plus) < abs(modifier.quality):
                break  # too much
            name = modifier.name + " " + name
            plus -= modifier.quality
            count += 1

        if plus < 0:
            name = f"{plus} {name}"
        if plus > 0:
            name = f"+{plus} {name}"

        logger.info("Gained %s %s", name, choice.value)
        self.equipment.put(choice, name)

    def win_item(self) -> None:
        self.inventory.add(special_item(), 1)


class Simulation:
    def __init__(self, player: Player) -> None:
        self.player = player
        self.last_tick = datetime.datetime.now()
        self.elapsed = 0.0

    def tick(self, elapsed: float = 100.0) -> None:
        if not self.player.task_bar.done:
            self.elapsed += elapsed
            self.player.task_bar.increment(elapsed)
            return

        # gain XP / level up
        gain = self.player.task and isinstance(self.player.task, KillTask)
        if gain:
            if self.player.exp_bar.done:
                self.player.level_up()
            else:
                self.player.exp_bar.increment(self.player.task_bar.max_ / 1000)

        # advance quest
        if gain and self.player.quest_book.act >= 1:
            if (
                self.player.quest_book.quest_bar.done
                or self.player.quest_book.current_quest is None
            ):
                self.complete_quest()
            else:
                self.player.quest_book.quest_bar.increment(
                    self.player.task_bar.max_ / 1000
                )

        # advance plot
        if gain:
            if self.player.quest_book.plot_bar.done:
                self.interplot_cinematic()
            else:
                self.player.quest_book.plot_bar.increment(
                    self.player.task_bar.max_ / 1000
                )

        self.dequeue()

    def dequeue(self) -> None:
        while self.player.task_bar.done:
            if isinstance(self.player.task, KillTask):
                if (
                    self.player.task.monster is None
                    or self.player.task.monster.item is None
                ):
                    # npc
                    self.player.win_item()
                elif self.player.task.monster.item:
                    self.player.inventory.add(
                        (
                            self.player.task.monster.name
                            + " "
                            + self.player.task.monster.item
                        ).lower(),
                        1,
                    )

            elif isinstance(self.player.task, BuyTask):
                # buy some equipment
                self.player.inventory.add_gold(-self.player.equip_price())
                self.player.win_equipment()

            elif isinstance(self.player.task, (HeadingToMarketTask, SellTask)):
                if isinstance(self.player.task, SellTask):
                    item = self.player.inventory[0]
                    amount = item.quantity * self.player.level
                    if " of " in item.name:
                        amount *= (1 + random.below_low(10)) * (
                            1 + random.below_low(self.player.level)
                        )
                    self.player.inventory.pop(0)
                    self.player.inventory.add_gold(amount)
                if len(self.player.inventory):
                    item = self.player.inventory[0]
                    self.player.set_task(
                        SellTask(
                            "Selling " + indefinite(item.name, item.quantity),
                            1_000,
                        )
                    )
                    break

            elif isinstance(self.player.task, PlotTask):
                self.complete_act()

            old = self.player.task
            if self.player.queue:
                self.player.set_task(self.player.queue.pop(0))
            elif self.player.inventory.encum_bar.done:
                self.player.set_task(
                    HeadingToMarketTask(
                        "Heading to market to sell loot", 4_000
                    )
                )
            elif not isinstance(old, (KillTask, HeadingToKillingFieldsTask)):
                if self.player.inventory.gold > self.player.equip_price():
                    self.player.set_task(
                        BuyTask(
                            "Negotiating purchase of better equipment", 5_000
                        )
                    )
                else:
                    self.player.set_task(
                        HeadingToKillingFieldsTask(
                            "Heading to the killing fields", 4_000
                        )
                    )
            else:
                self.player.set_task(
                    monster_task(
                        self.player.level, self.player.quest_book.monster
                    )
                )

    def complete_act(self) -> None:
        self.player.quest_book.act += 1
        self.player.quest_book.plot_bar.reset(
            60 * 60 * (1 + 5 * self.player.quest_book.act)
        )
        if self.player.quest_book.act > 1:
            self.player.win_item()
            self.player.win_equipment()
        self.player.quest_book.emit("complete_act")

    def complete_quest(self) -> None:
        self.player.quest_book.quest_bar.reset(50 + random.below_low(1000))
        if self.player.quest_book.current_quest:
            logger.info(
                "Quest completed: %s", self.player.quest_book.current_quest
            )
            random.choice(
                [
                    self.player.win_spell,
                    self.player.win_equipment,
                    self.player.win_stat,
                    self.player.win_item,
                ]
            )()

        self.player.quest_book.monster = None
        caption = ""
        choice = random.below(5)
        if choice == 0:
            self.player.quest_book.monster = unnamed_monster(
                self.player.level, iterations=3
            )
            caption = "Exterminate " + definite(
                self.player.quest_book.monster.name, 2
            )
        elif choice == 1:
            caption = "Seek " + definite(interesting_item(), 1)
        elif choice == 2:
            caption = "Deliver this " + boring_item()
        elif choice == 3:
            caption = "Fetch me " + indefinite(boring_item(), 1)
        elif choice == 4:
            monster = unnamed_monster(self.player.level, iterations=1)
            caption = "Placate " + definite(monster.name, 2)
        else:
            raise AssertionError

        self.player.quest_book.add_quest(caption)
        self.player.quest_book.emit("complete_quest")

    def interplot_cinematic(self) -> None:
        def enqueue(task: BaseTask) -> None:
            self.player.queue.append(task)
            self.dequeue()

        choice = random.below(3)
        if choice == 0:
            enqueue(
                RegularTask(
                    "Exhausted, you arrive at a friendly oasis "
                    "in a hostile land",
                    1_000,
                )
            )
            enqueue(
                RegularTask("You greet old friends and meet new allies", 2_000)
            )
            enqueue(
                RegularTask(
                    "You are privy to a council of powerful do-gooders", 2_000
                )
            )
            enqueue(
                RegularTask("There is much to be done. You are chosen!", 1_000)
            )

        elif choice == 1:
            enqueue(
                RegularTask(
                    "Your quarry is in sight, "
                    "but a mighty enemy bars your path!",
                    1_000,
                )
            )

            nemesis = named_monster(self.player.level + 3)

            enqueue(
                RegularTask(
                    f"A desperate struggle commences with {nemesis}", 4_000
                )
            )

            s = random.below(3)
            for i in itertools.count(start=1):
                if i > random.below(1 + self.player.quest_book.act + 1):
                    break
                s += 1 + random.below(2)
                if s % 3 == 0:
                    enqueue(
                        RegularTask(
                            f"Locked in grim combat with {nemesis}", 2_000
                        )
                    )
                elif s % 3 == 1:
                    enqueue(
                        RegularTask(
                            f"{nemesis} seems to have the upper hand", 2_000
                        )
                    )
                elif s % 3 == 2:
                    enqueue(
                        RegularTask(
                            f"You seem to gain the advantage over {nemesis}",
                            2_000,
                        )
                    )
                else:
                    raise AssertionError()

            enqueue(
                RegularTask(
                    f"Victory! {nemesis} is slain! "
                    "Exhausted, you lose conciousness",
                    3_000,
                )
            )
            enqueue(
                RegularTask(
                    "You awake in a friendly place, but the road awaits", 2_000
                )
            )

        elif choice == 2:
            nemesis = impressive_guy()
            enqueue(
                RegularTask(
                    "Oh sweet relief! "
                    f"You've reached the protection of the good {nemesis}",
                    2_000,
                )
            )
            enqueue(
                RegularTask(
                    "There is rejoicing, "
                    f"and an unnerving encouter with {nemesis} in private",
                    3_000,
                )
            )
            enqueue(
                RegularTask(
                    f"You forget your {boring_item()} and go back to get it",
                    2_000,
                )
            )
            enqueue(
                RegularTask(
                    "What's this!? You overhear something shocking!", 2_000
                )
            )
            enqueue(
                RegularTask(
                    f"Could {nemesis} be a dirty double-dealer?", 2_000
                )
            )
            enqueue(
                RegularTask(
                    "Who can possibly be trusted with this news!? ... "
                    "Oh yes, of course",
                    3_000,
                )
            )

        else:
            raise AssertionError

        enqueue(
            PlotTask(
                f"Loading {act_name(self.player.quest_book.act + 1)}", 1_000
            )
        )


def special_item() -> str:
    return interesting_item() + " of " + T.cast(str, random.choice(ITEM_OFS))


def interesting_item() -> str:
    return (
        T.cast(str, random.choice(ITEM_ATTRIB))
        + " "
        + T.cast(str, random.choice(SPECIALS))
    )


def boring_item() -> str:
    return T.cast(str, random.choice(BORING_ITEMS))


def impressive_guy() -> str:
    return T.cast(str, random.choice(IMPRESSIVE_TITLES)) + (
        " of the " + T.cast(Race, random.choice(RACES)).name
        if random.below(2)
        else " of " + generate_name()
    )


def unnamed_monster(level: int, iterations: int) -> Monster:
    result = T.cast(Monster, random.choice(MONSTERS))
    for _ in range(iterations):
        alternative = T.cast(Monster, random.choice(MONSTERS))
        if abs(level - alternative.level) < abs(level - result.level):
            result = alternative
    return result


def named_monster(level: int) -> str:
    monster = unnamed_monster(level, iterations=4)
    return generate_name() + " the " + monster.name


def pick_equipment(
    source: T.List[EquipmentPreset], goal: int
) -> EquipmentPreset:
    result = T.cast(EquipmentPreset, random.choice(source))
    for _ in range(5):
        alternative = T.cast(EquipmentPreset, random.choice(source))
        if abs(goal - alternative.quality) < abs(goal - result.quality):
            result = alternative
    return result


def monster_task(
    player_level: int, quest_monster: T.Optional[Monster]
) -> KillTask:
    level = player_level
    for _ in range(level):
        if random.odds(2, 5):
            level += random.below(2) * 2 - 1
    if level < 1:
        level = 1

    is_definite = False
    monster: T.Optional[Monster] = None
    if random.odds(1, 25):
        # use an NPC every once in a while
        race = random.choice(RACES)
        if random.odds(1, 2):
            result = "passing " + race.name + " " + random.choice(CLASSES).name
        else:
            result = (
                random.choice_low(TITLES)
                + " "
                + generate_name()
                + " the "
                + race.name
            )
            is_definite = True
        lev = level
    elif quest_monster and random.odds(1, 4):
        # use the quest monster
        monster = quest_monster
        result = monster.name
        lev = monster.level
    else:
        # pick the monster out of so many random ones closest to the level we want
        monster = unnamed_monster(level, iterations=5)
        result = monster.name
        lev = monster.level

    qty = 1
    if level - lev > 10:
        # lev is too low. multiply
        qty = (level + random.below(max(lev, 1))) // max(lev, 1)
        if qty < 1:
            qty = 1
        level //= qty

    if level - lev <= -10:
        result = "imaginary " + result
    elif level - lev < -5:
        i = 10 + level - lev
        i = 5 - random.below(i + 1)
        result = sick(i, young(lev - level - i, result))
    elif level - lev < 0 and random.below(2) == 1:
        result = sick(level - lev, result)
    elif level - lev < 0:
        result = young(level - lev, result)
    elif level - lev >= 10:
        result = "messianic " + result
    elif level - lev > 5:
        i = 10 - (level - lev)
        i = 5 - random.below(i + 1)
        result = big(i, special(level - lev - i, result))
    elif level - lev > 0 and random.below(2) == 1:
        result = big(level - lev, result)
    elif level - lev > 0:
        result = special(level - lev, result)

    lev = level
    level = lev * qty
    if not is_definite:
        result = indefinite(result, qty)

    duration = (2 * 3 * level * 1000) // player_level
    return KillTask(f"Executing {result}", duration, monster=monster)


class StatsBuilder:
    def __init__(self) -> None:
        self.history: T.List[Stats] = []

    def roll(self) -> Stats:
        values: T.Dict[StatType, int] = {
            stat: 3 + random.below(6) + random.below(6) + random.below(6)
            for stat in PRIME_STATS
        }
        values[StatType.hp_max] = (
            random.below(8) + values[StatType.condition] // 6
        )
        values[StatType.mp_max] = (
            random.below(8) + values[StatType.intelligence] // 6
        )
        stats = Stats(values)
        self.history.append(stats)
        return stats

    def unroll(self) -> Stats:
        self.history.pop()
        return self.history[-1]


def create_player(
    name: str, race: Race, class_: Class, stats: Stats
) -> Player:
    now = datetime.datetime.now()
    random.seed(now)
    return Player(
        birthday=now, name=name, race=race, class_=class_, stats=stats
    )
