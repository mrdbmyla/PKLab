import engine
from pokedata import ABILITIES, NATURES


def _ability_and_nature(species, pid, ability_slot):
    ability = None
    ab = ABILITIES.get(species)
    if ab:
        a1, a2, _hidden = ab
        ability = a2 if (a2 and ability_slot == 1) else a1
    nature = NATURES.get((pid % 25) + 1)
    return ability, nature


def finalize_gen3_mon(raw_mon):
    ability, nature = _ability_and_nature(raw_mon["species"], raw_mon["pid"], raw_mon["abilitySlot"])
    pid = raw_mon["pid"]
    otid = raw_mon.get("otid")
    shiny = otid is not None and ((otid >> 16) ^ (otid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)) < engine.SHINY_THRESHOLD
    return {
        "species": raw_mon["species"], "hpCur": raw_mon["hpCur"], "hpMax": raw_mon["hpMax"],
        "level": raw_mon["level"], "ability": ability, "nature": nature, "ivs": raw_mon["ivs"],
        "pid": pid, "shiny": shiny,
    }
