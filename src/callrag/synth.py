"""Generates synthetic call transcripts for home-service businesses.

Everything here is invented: the companies, the people, the phone numbers (the reserved
555-01xx range), the email addresses (example.com), the addresses and the card numbers (random,
with a valid check digit). No real call was used as a source or a template.

The generator records where every piece of personal information sits in every turn, by
character position. That record is the answer key the redaction evaluation is scored against.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Pii:
    turn: int
    start: int
    end: int
    kind: str  # NAME, PHONE, EMAIL, ADDRESS, CARD
    form: str  # how it was said: see FORMS in evaluate.py
    value: str


@dataclass(frozen=True)
class Turn:
    speaker: str  # "agent" or "caller"
    text: str


@dataclass(frozen=True)
class Call:
    call_id: str
    tenant_id: str
    started_at: str
    caller_name: str  # what the business's CRM would hold for this caller
    agent_name: str
    topic: str
    brand: str
    location: str
    turns: tuple[Turn, ...]
    pii: tuple[Pii, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> Call:
        raw: dict[str, Any] = json.loads(line)
        raw["turns"] = tuple(Turn(**t) for t in raw["turns"])
        raw["pii"] = tuple(Pii(**p) for p in raw["pii"])
        return cls(**raw)


@dataclass(frozen=True)
class Topic:
    key: str
    said: tuple[str, ...]  # how a caller describes it; {brand} and {location} are filled in
    paraphrase: str  # the same problem in words the callers never use
    questions: tuple[tuple[str, str], ...]  # (agent question, caller answer)
    brands: tuple[str, ...]
    locations: tuple[str, ...]


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    company: str
    agents: tuple[str, ...]
    topics: tuple[Topic, ...]


TENANTS: tuple[Tenant, ...] = (
    Tenant(
        "delta-plumbing",
        "Delta Plumbing",
        ("Priya", "Marcus", "Elena"),
        (
            Topic(
                "water_heater_leak",
                (
                    "my {brand} water heater in the {location} is leaking from the bottom",
                    "there is water pooling under the {brand} water heater in the {location}",
                ),
                "hot water tank dripping onto the floor",
                (
                    ("How old is the tank?", "About twelve years, it came with the house."),
                    ("Is the water still hot?", "Lukewarm at best since yesterday."),
                ),
                ("Rheem", "Bradford White", "AO Smith"),
                ("garage", "basement", "hall closet"),
            ),
            Topic(
                "clogged_drain",
                (
                    "the {location} drain is completely clogged and the {brand} cleaner did "
                    "nothing",
                    "water will not go down the {location} drain, I already tried {brand}",
                ),
                "sink backing up and not emptying",
                (
                    ("Is it one fixture or several?", "Just that one, the others drain fine."),
                    ("Any gurgling sounds?", "Yes, it gurgles when the washer runs."),
                ),
                ("Drano", "Liquid Plumr", "Green Gobbler"),
                ("kitchen sink", "upstairs shower", "laundry room"),
            ),
            Topic(
                "running_toilet",
                (
                    "the {brand} toilet in the {location} keeps running all night",
                    "our {location} toilet, a {brand}, never stops filling",
                ),
                "commode constantly refilling its cistern",
                (
                    ("Does jiggling the handle stop it?", "For a minute, then it starts again."),
                    ("Have you seen the water bill go up?", "It nearly doubled this month."),
                ),
                ("Kohler", "Toto", "American Standard"),
                ("master bathroom", "guest bathroom", "downstairs half bath"),
            ),
            Topic(
                "burst_pipe",
                (
                    "a pipe burst behind the wall in the {location} and I shut off the main, "
                    "it is {brand} piping",
                    "we have a burst {brand} pipe flooding the {location}",
                ),
                "ruptured supply line soaking the drywall",
                (
                    ("Is the main shutoff closed?", "Yes, I closed it at the street."),
                    ("How much water is on the floor?", "About an inch across the room."),
                ),
                ("copper", "PEX", "galvanized"),
                ("crawl space", "utility room", "kitchen"),
            ),
            Topic(
                "low_water_pressure",
                (
                    "the water pressure in the {location} dropped to a trickle, the fixture is "
                    "a {brand}",
                    "barely any pressure at the {brand} faucet in the {location}",
                ),
                "weak flow from the tap",
                (
                    ("Hot, cold or both?", "Both sides are weak."),
                    ("Did it happen suddenly?", "Over about a week."),
                ),
                ("Moen", "Delta", "Pfister"),
                ("primary shower", "kitchen", "backyard spigot"),
            ),
            Topic(
                "garbage_disposal",
                (
                    "the {brand} garbage disposal under the {location} just hums and will not spin",
                    "my {brand} disposal at the {location} is jammed and smells",
                ),
                "food grinder seized up below the basin",
                (
                    ("Did you try the reset button?", "Yes, it clicks but nothing changes."),
                    ("Anything fall in recently?", "Possibly a bottle cap."),
                ),
                ("InSinkErator", "Waste King", "Moen"),
                ("kitchen sink", "bar sink", "prep sink"),
            ),
        ),
    ),
    Tenant(
        "valley-air",
        "Valley Air Heating and Cooling",
        ("Jordan", "Sam", "Renee"),
        (
            Topic(
                "ac_warm_air",
                (
                    "the {brand} air conditioner is blowing warm air in the {location}",
                    "our {brand} AC runs but the {location} never cools down",
                ),
                "cooling system pushing out heat instead of cold",
                (
                    ("Is the outdoor unit running?", "The fan spins but it sounds rough."),
                    ("When was the filter last changed?", "Honestly, more than a year ago."),
                ),
                ("Carrier", "Trane", "Lennox"),
                ("upstairs bedrooms", "living room", "whole house"),
            ),
            Topic(
                "furnace_no_ignite",
                (
                    "the {brand} furnace in the {location} clicks but will not ignite",
                    "no heat, the {brand} furnace in the {location} tries to start and shuts off",
                ),
                "heater failing to light its burners",
                (
                    ("Do you see a blinking light code?", "Three blinks, then a pause."),
                    ("Do you smell gas?", "No smell at all."),
                ),
                ("Goodman", "Rheem", "Bryant"),
                ("attic", "garage", "hallway closet"),
            ),
            Topic(
                "thermostat_blank",
                (
                    "the {brand} thermostat in the {location} went blank and nothing responds",
                    "my {brand} thermostat screen in the {location} is dead",
                ),
                "wall controller display has no power",
                (
                    ("Have you replaced the batteries?", "Twice, with new ones."),
                    ("Did a breaker trip?", "I checked, they all look fine."),
                ),
                ("Nest", "Ecobee", "Honeywell"),
                ("hallway", "living room", "upstairs landing"),
            ),
            Topic(
                "frozen_coil",
                (
                    "there is ice all over the {brand} unit's line by the {location}",
                    "the {brand} evaporator by the {location} is frozen solid",
                ),
                "frost build-up on the refrigerant tubing",
                (
                    ("Is air still coming from the vents?", "Very little, and it is not cold."),
                    ("How long has it been running?", "Nonstop since Saturday."),
                ),
                ("Carrier", "York", "Daikin"),
                ("side yard", "attic", "garage"),
            ),
            Topic(
                "loud_noise",
                (
                    "the {brand} unit outside the {location} makes a loud grinding noise at "
                    "startup",
                    "a banging sound comes from the {brand} condenser near the {location}",
                ),
                "compressor rattling and screeching when it kicks on",
                (
                    ("Does it stop after a few seconds?", "No, it keeps going until it shuts off."),
                    ("Any burning smell?", "A little, like hot metal."),
                ),
                ("Trane", "Lennox", "American Standard"),
                ("back patio", "bedroom window", "driveway"),
            ),
            Topic(
                "duct_leak",
                (
                    "one room, the {location}, gets no air and I think a {brand} duct came loose",
                    "no airflow to the {location}, the {brand} ducting may be disconnected",
                ),
                "ventilation run detached so a space gets nothing",
                (
                    ("Are the other rooms fine?", "Every other room is comfortable."),
                    ("Has anyone been in the attic?", "The cable installer was up there."),
                ),
                ("flex", "sheet metal", "insulated"),
                ("nursery", "home office", "bonus room"),
            ),
        ),
    ),
    Tenant(
        "brightline-electric",
        "Brightline Electric",
        ("Dana", "Luis", "Mei"),
        (
            Topic(
                "breaker_trips",
                (
                    "the breaker for the {location} keeps tripping in our {brand} panel",
                    "every time we run the microwave the {location} breaker trips, {brand} panel",
                ),
                "circuit protection cutting out repeatedly",
                (
                    ("Does it trip immediately?", "After about ten seconds of use."),
                    ("Is the breaker warm to the touch?", "Yes, noticeably warm."),
                ),
                ("Square D", "Siemens", "Eaton"),
                ("kitchen", "garage", "bathroom"),
            ),
            Topic(
                "outlet_dead",
                (
                    "the {brand} outlets along the {location} wall stopped working",
                    "half the {brand} outlets in the {location} are dead",
                ),
                "receptacles with no power",
                (
                    ("Did you press the reset on any GFCI?", "I could not find one."),
                    ("Any scorch marks?", "One cover plate looks a bit brown."),
                ),
                ("Leviton", "Lutron", "Legrand"),
                ("living room", "primary bedroom", "patio"),
            ),
            Topic(
                "flickering_lights",
                (
                    "the {brand} lights in the {location} flicker whenever the dryer runs",
                    "our {location} lights, {brand} fixtures, dim and flicker at night",
                ),
                "lamps pulsing and dipping in brightness",
                (
                    ("Is it one room or the whole house?", "Mostly that room, sometimes the hall."),
                    ("Are the bulbs new?", "All replaced last month."),
                ),
                ("Philips", "Halo", "Lithonia"),
                ("dining room", "kitchen", "hallway"),
            ),
            Topic(
                "ev_charger_install",
                (
                    "I need a {brand} EV charger installed in the {location}",
                    "looking for a quote to put a {brand} charger in the {location}",
                ),
                "set up a station to power an electric car at home",
                (
                    ("Do you know your panel's amperage?", "It says 100 amps on the main."),
                    ("How far is the panel from the spot?", "Maybe thirty feet."),
                ),
                ("Tesla", "ChargePoint", "Emporia"),
                ("garage", "carport", "driveway"),
            ),
            Topic(
                "panel_buzzing",
                (
                    "the {brand} panel in the {location} is buzzing and smells hot",
                    "there is a humming noise from our {brand} breaker box in the {location}",
                ),
                "distribution board making a droning sound",
                (
                    ("Is any breaker discolored?", "The top left one looks darker."),
                    ("Have you turned anything off?", "I shut off the main to be safe."),
                ),
                ("Zinsco", "Federal Pacific", "Square D"),
                ("garage", "laundry room", "side of the house"),
            ),
            Topic(
                "ceiling_fan",
                (
                    "the {brand} ceiling fan in the {location} wobbles and the light cut out",
                    "our {brand} fan in the {location} stopped responding to the remote",
                ),
                "overhead blower unstable and unlit",
                (
                    ("Does the wall switch do anything?", "The fan spins but there is no light."),
                    ("How high is the ceiling?", "About twelve feet."),
                ),
                ("Hunter", "Minka", "Casablanca"),
                ("family room", "primary bedroom", "covered patio"),
            ),
        ),
    ),
)

FIRST = tuple(
    "Maria James Aisha Daniel Sofia Kevin Hannah Omar Grace Victor Naomi Ethan Lucia Brandon "
    "Yuki Andre Carmen Tyler".split()
)
LAST = tuple(
    "Lopez Nguyen Patel Okafor Romero Kowalski Tanaka Reyes Lindqvist Haddad Castillo Brennan "
    "Sato Whitfield Mendoza".split()
)
RELATIONS = ("husband", "wife", "son", "daughter", "neighbor", "tenant", "roommate", "mother")
STREETS = (
    "Alder",
    "Birch",
    "Juniper",
    "Manzanita",
    "Sycamore",
    "Larkspur",
    "Quail Hollow",
    "Copper Ridge",
    "Willow Bend",
    "Stone Creek",
)
SUFFIXES = ("Street", "Avenue", "Court", "Way", "Drive", "Lane")
CITIES = ("Oakmont", "Riverbend", "Cedar Grove", "Marlow", "Fairhaven")
AREA_CODES = ("916", "530", "209")
DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
WINDOWS = ("8 and 10", "10 and 12", "1 and 3", "3 and 5")


class _Text:
    """Builds one turn, remembering where the personal information went."""

    def __init__(self, turn: int) -> None:
        self.turn = turn
        self.parts: list[str] = []
        self.pii: list[Pii] = []
        self._length = 0

    def add(self, text: str) -> _Text:
        self.parts.append(text)
        self._length += len(text)
        return self

    def secret(self, value: str, kind: str, form: str) -> _Text:
        self.pii.append(Pii(self.turn, self._length, self._length + len(value), kind, form, value))
        return self.add(value)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _luhn_complete(prefix: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(prefix)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return prefix + str((10 - total % 10) % 10)


def luhn_valid(digits: str) -> bool:
    return len(digits) > 1 and _luhn_complete(digits[:-1]) == digits


def _card(rng: random.Random) -> str:
    # 4000 00 is the prefix payment processors use for test cards. The rest is random.
    number = _luhn_complete("400000" + "".join(rng.choice("0123456789") for _ in range(9)))
    style = rng.choice(("spaces", "dashes", "plain"))
    groups = [number[i : i + 4] for i in range(0, 16, 4)]
    return {"spaces": " ".join(groups), "dashes": "-".join(groups), "plain": number}[style]


def _not_a_card(rng: random.Random) -> str:
    """A 16-digit confirmation code that fails the card check digit."""
    while True:
        digits = "".join(rng.choice("0123456789") for _ in range(16))
        if not luhn_valid(digits):
            return " ".join(digits[i : i + 4] for i in range(0, 16, 4))


def _call(rng: random.Random, tenant: Tenant, number: int, day: dt.date) -> Call:
    topic = rng.choice(tenant.topics)
    brand, location = rng.choice(topic.brands), rng.choice(topic.locations)
    first, last = rng.choice(FIRST), rng.choice(LAST)
    agent = rng.choice(tenant.agents)
    turns: list[Turn] = []
    pii: list[Pii] = []

    def say(speaker: str) -> _Text:
        return _Text(len(turns))

    def done(speaker: str, text: _Text) -> None:
        turns.append(Turn(speaker, text.text))
        pii.extend(text.pii)

    t = say("agent").add(f"Thanks for calling {tenant.company}, this is ")
    done("agent", t.secret(agent, "NAME", "agent").add(". How can I help?"))

    t = say("caller")
    intro = rng.choice(("Hi, my name is ", "Hello, this is ", "Hi, it's ", "Yeah, I'm "))
    t.add(intro).secret(f"{first} {last}", "NAME", "introduced").add(". ")
    statement = rng.choice(topic.said).format(brand=brand, location=location)
    done("caller", t.add(statement[0].upper() + statement[1:] + "."))

    for question, answer in topic.questions:
        done("agent", say("agent").add(question))
        done("caller", say("caller").add(answer))

    if rng.random() < 0.35:
        t = say("agent").add("Do you have the model or serial number handy?")
        done("agent", t)
        model = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(9))
        serial = "".join(rng.choice("0123456789") for _ in range(10))
        t = say("caller").add(f"The model is {brand.split()[0].upper()}-{model} and the serial ")
        done("caller", t.add(f"number is {serial}."))

    t = say("agent").add("Thanks, ")
    done("agent", t.secret(first, "NAME", "known").add(". What is the service address?"))
    t = say("caller")
    street = f"{rng.randint(100, 9899)} {rng.choice(STREETS)} {rng.choice(SUFFIXES)}"
    roll = rng.random()
    if roll < 0.55:
        full = f"{street}, {rng.choice(CITIES)}, CA {rng.randint(95600, 95899)}"
        t.add("It is ").secret(full, "ADDRESS", "full").add(".")
    elif roll < 0.75:
        unit = f"{street}, Apt {rng.randint(1, 40)}{rng.choice('ABCD')}"
        t.add("We are at ").secret(unit, "ADDRESS", "with unit").add(".")
    elif roll < 0.90:
        t.add("it's ").secret(street.lower(), "ADDRESS", "lowercase").add(" in town")
    else:
        vague = f"the blue house on {rng.choice(STREETS)} past the school"
        t.add("Hard to explain, it is ").secret(vague, "ADDRESS", "described").add(".")
    done("caller", t)

    done("agent", say("agent").add("And the best number to reach you?"))
    area, line = rng.choice(AREA_CODES), f"01{rng.randint(0, 99):02d}"
    t = say("caller")
    roll = rng.random()
    if roll < 0.35:
        t.secret(f"({area}) 555-{line}", "PHONE", "formatted")
    elif roll < 0.60:
        t.secret(f"{area}-555-{line}", "PHONE", "formatted")
    elif roll < 0.75:
        t.secret(f"{area}.555.{line}", "PHONE", "formatted")
    elif roll < 0.85:
        t.secret(f"{area}555{line}", "PHONE", "digits only")
    else:
        spoken = " ".join(DIGIT_WORDS[int(d)] for d in f"{area}555{line}")
        t.secret(spoken, "PHONE", "spoken")
    done("caller", t.add(rng.choice((".", ", that's my cell.", ", call or text."))))

    if rng.random() < 0.60:
        done("agent", say("agent").add("Can I get an email for the confirmation?"))
        t = say("caller").add("Sure, ")
        local = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}"
        if rng.random() < 0.85:
            t.secret(f"{local}@example.com", "EMAIL", "written")
        else:
            said = local.replace(".", " dot ") + " at example dot com"
            t.secret(said, "EMAIL", "spoken")
        done("caller", t.add("."))

    if rng.random() < 0.25:
        t = say("agent").add("There is an 89 dollar dispatch fee. Which card should I use?")
        done("agent", t)
        t = say("caller").add("Use ").secret(_card(rng), "CARD", "written")
        done("caller", t.add(f", expires {rng.randint(1, 12):02d}/{rng.randint(27, 31)}."))

    if rng.random() < 0.30:
        other = rng.choice([n for n in FIRST if n != first])
        t = say("caller")
        if rng.random() < 0.6:
            t.add(f"I will be at work, but my {rng.choice(RELATIONS)} ")
            t.secret(other, "NAME", "relative").add(" will be home.")
        else:
            t.add("I will be at work. ").secret(other, "NAME", "bare")
            t.add(" will let the technician in.")
        done("caller", t)

    slot_day, window = rng.choice(DAYS), rng.choice(WINDOWS)
    t = say("agent").add(f"I have you down for {slot_day} between {window}. ")
    t.add(f"Your job number is J-{rng.randint(10000, 99999)}")
    if rng.random() < 0.3:
        t.add(f" and your confirmation code is {_not_a_card(rng)}")
    done("agent", t.add("."))

    t = say("caller").add(rng.choice(("Perfect, thank you.", "Great, see you then.", "Thanks.")))
    done("caller", t)
    t = say("agent").add("You are welcome, ").secret(first, "NAME", "known")
    done("agent", t.add(f". Thanks for choosing {tenant.company}."))

    started = dt.datetime.combine(day, dt.time(8), dt.UTC) + dt.timedelta(
        minutes=rng.randint(0, 600)
    )
    return Call(
        call_id=f"{tenant.tenant_id}-{number:05d}",
        tenant_id=tenant.tenant_id,
        started_at=started.isoformat(),
        caller_name=f"{first} {last}",
        agent_name=agent,
        topic=topic.key,
        brand=brand,
        location=location,
        turns=tuple(turns),
        pii=tuple(pii),
    )


def generate(calls_per_tenant: int = 200, seed: int = 7, start: int = 0) -> list[Call]:
    """Deterministic for a given seed: the same call numbers always produce the same calls."""
    out: list[Call] = []
    first_day = dt.date(2026, 9, 1)
    for tenant in TENANTS:
        for number in range(start, start + calls_per_tenant):
            # Each call has its own seed, so adding calls never changes earlier ones.
            digest = hashlib.sha256(f"{seed}/{tenant.tenant_id}/{number}".encode()).digest()
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            out.append(_call(rng, tenant, number, first_day + dt.timedelta(days=number % 60)))
    return out


def topic_of(call: Call) -> Topic:
    tenant = next(t for t in TENANTS if t.tenant_id == call.tenant_id)
    return next(t for t in tenant.topics if t.key == call.topic)


def write_jsonl(calls: Sequence[Call], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for call in calls:
            handle.write(call.to_json() + "\n")


def read_jsonl(path: Path) -> Iterator[Call]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield Call.from_json(line)
