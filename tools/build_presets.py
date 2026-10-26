from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

SPECS: dict[str, dict[str, Any]] = {
    "balance_druid": {
        "class": "druid",
        "spec": "balance",
        "field": "balanceDruid",
        "path": "druid/balance",
        "gear": "preraid",
        "rotation": "default",
        "talents": "510022312503135231351--520033",
        "races": ["night_elf", "tauren"],
        "distance": 20,
        "options": {"classOptions": {"innervateTarget": {}}},
        "consumables": {
            "conjuredId": 12662,
            "drumsId": 4,
            "flaskId": 22861,
            "foodId": 27657,
            "mhImbueId": 25122,
            "potId": 22832,
        },
    },
    "feral_druid": {
        "class": "druid",
        "spec": "feral_cat",
        "field": "feralCatDruid",
        "path": "druid/feralcat",
        "gear": "pre_raid",
        "rotation": "default",
        "talents": "-503032132322105301251-05503301",
        "races": ["night_elf", "tauren"],
        "distance": 0,
        "reaction_time_ms": 250,
        "consumables": {
            "potId": 22838,
            "battleElixirId": 22831,
            "guardianElixirId": 32067,
            "foodId": 27664,
            "mhImbueId": 34340,
            "conjuredId": 12662,
            "drumsId": 1,
            "superSapper": True,
            "goblinSapper": True,
            "scrollAgi": True,
            "scrollStr": True,
        },
    },
    "beast_mastery_hunter": {
        "class": "hunter",
        "spec": "beast_mastery",
        "field": "hunter",
        "build": "hunter/dps/builds/phase_1/bm/pre_raid.build.json",
        "races": [
            "dwarf",
            "night_elf",
            "draenei",
            "orc",
            "tauren",
            "troll",
            "blood_elf",
        ],
    },
    "arcane_mage": {
        "class": "mage",
        "spec": "arcane",
        "field": "mage",
        "path": "mage/dps",
        "gear": "preBisArcane",
        "rotation": "arcane",
        "talents": "2500052300030150330125--053500031003001",
        "races": ["human", "gnome", "draenei", "undead", "troll", "blood_elf"],
        "distance": 20,
        "options": {"classOptions": {"defaultMageArmor": "MageArmorMageArmor"}},
        "consumables": {
            "guardianElixirId": 32067,
            "battleElixirId": 28103,
            "foodId": 27657,
            "mhImbueId": 25122,
            "potId": 22832,
        },
    },
    "retribution_paladin": {
        "class": "paladin",
        "spec": "retribution",
        "field": "retributionPaladin",
        "path": "paladin/retribution",
        "gear": "preraid",
        "rotation": "default",
        "talents": "5-053201-0523005120033125331051",
        "races": ["human", "dwarf", "draenei", "blood_elf"],
        "distance": 5,
        "consumables": {
            "potId": 22838,
            "flaskId": 22854,
            "foodId": 27658,
            "conjuredId": 12662,
            "superSapper": True,
            "goblinSapper": True,
            "scrollAgi": True,
            "scrollStr": True,
            "explosiveId": 30217,
        },
    },
    "shadow_priest": {
        "class": "priest",
        "spec": "shadow",
        "field": "priest",
        "path": "priest/dps",
        "gear": "pre_raid",
        "rotation": "default",
        "talents": "500230013--503250510240103051451",
        "races": [
            "human",
            "dwarf",
            "night_elf",
            "draenei",
            "undead",
            "troll",
            "blood_elf",
        ],
        "distance": 28,
        "channel_clip_delay_ms": 100,
    },
    "rogue": {
        "class": "rogue",
        "spec": "combat",
        "field": "rogue",
        "path": "rogue/dps",
        "gear": "p1",
        "rotation": "swords",
        "talents": "00532012502-023305200005015002321151",
        "races": [
            "human",
            "dwarf",
            "night_elf",
            "gnome",
            "orc",
            "undead",
            "troll",
            "blood_elf",
        ],
        "distance": 5,
        "consumables": {
            "flaskId": 22854,
            "foodId": 33872,
            "potId": 22838,
            "conjuredId": 7676,
            "ohImbueId": 27186,
        },
    },
    "elemental_shaman": {
        "class": "shaman",
        "spec": "elemental",
        "field": "elementalShaman",
        "path": "shaman/elemental",
        "gear": "preraid",
        "rotation": "default",
        "talents": "55003105100213351051--05105301005",
        "races": ["draenei", "orc", "tauren", "troll"],
        "distance": 20,
        "options": {"classOptions": {"shieldProcrate": 0}},
        "consumables": {
            "conjuredId": 12662,
            "drumsId": 4,
            "flaskId": 22861,
            "foodId": 27657,
            "mhImbueId": 25122,
            "potId": 22839,
        },
    },
    "enhancement_shaman": {
        "class": "shaman",
        "spec": "enhancement",
        "field": "enhancementShaman",
        "path": "shaman/enhancement",
        "gear": "preraid",
        "rotation": "default",
        "talents": "03-500502210501133531151-50005301",
        "races": ["draenei", "orc", "tauren", "troll"],
        "distance": 5,
        "options": {
            "classOptions": {"shieldProcrate": 0, "imbueMh": "WindfuryWeapon"},
            "imbueOh": "WindfuryWeapon",
            "syncType": "DelayOffhandSwings",
        },
        "consumables": {
            "potId": 22838,
            "flaskId": 22854,
            "foodId": 27658,
            "drumsId": 4,
            "conjuredId": 22788,
            "explosiveId": 30217,
            "superSapper": True,
            "goblinSapper": True,
            "scrollAgi": True,
            "scrollStr": True,
        },
    },
    "affliction_warlock": {
        "class": "warlock",
        "spec": "affliction",
        "field": "warlock",
        "path": "warlock/dps",
        "gear": "preraid",
        "rotation": "affliction",
        "talents": "05022221112351055003--50500051220001",
        "races": ["human", "gnome", "orc", "undead", "blood_elf"],
        "distance": 20,
        "options": {
            "classOptions": {
                "armor": "FelArmor",
                "curseOptions": "Elements",
                "sacrificeSummon": False,
                "summon": "Imp",
            }
        },
        "consumables": {
            "flaskId": 22866,
            "foodId": 27657,
            "conjuredId": 12662,
            "mhImbueId": 25122,
            "potId": 22839,
            "explosiveId": 30217,
            "petScrollAgi": True,
            "petScrollStr": True,
        },
    },
    "destruction_warlock": {
        "class": "warlock",
        "spec": "destruction",
        "field": "warlock",
        "path": "warlock/dps",
        "gear": "preraid",
        "rotation": "destruction",
        "talents": "-20500301332101-50500051220051053105",
        "races": ["human", "gnome", "orc", "undead", "blood_elf"],
        "distance": 20,
        "options": {
            "classOptions": {
                "armor": "FelArmor",
                "curseOptions": "Recklessness",
                "sacrificeSummon": True,
                "summon": "Succubus",
            }
        },
        "consumables": {
            "flaskId": 22866,
            "foodId": 27657,
            "conjuredId": 12662,
            "mhImbueId": 25122,
            "potId": 22839,
            "explosiveId": 30217,
            "petScrollAgi": True,
            "petScrollStr": True,
        },
    },
    "fury_warrior": {
        "class": "warrior",
        "spec": "fury",
        "field": "dpsWarrior",
        "path": "warrior/dps",
        "gear": "preraid_fury",
        "rotation": "fury",
        "talents": "3400502130201-05050005505012050115",
        "races": [
            "human",
            "dwarf",
            "night_elf",
            "gnome",
            "draenei",
            "orc",
            "undead",
            "tauren",
            "troll",
        ],
        "distance": 5,
        "options": {
            "classOptions": {
                "queueDelay": 250,
                "startingRage": 50,
                "defaultShout": "WarriorShoutBattle",
                "defaultStance": "WarriorStanceBerserker",
                "hasBsT2": True,
                "stanceSnapshot": True,
            }
        },
        "consumables": {
            "flaskId": 22854,
            "foodId": 33872,
            "potId": 22838,
            "conjuredId": 7676,
            "ohImbueId": 27186,
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.source / "ui" / "specs"
    manifest = {
        "version": 1,
        "sim_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.source, text=True
        ).strip(),
        "specs": {},
    }
    for key, config in SPECS.items():
        entry = {
            k: v
            for k, v in config.items()
            if k not in {"path", "gear", "rotation", "build"}
        }
        if "build" in config:
            build = json.loads((root / config["build"]).read_text())
            player = build["player"]
            entry.update(
                equipment=player["equipment"],
                rotation=player["rotation"],
                talents=player["talentsString"],
                consumables=player.get("consumables", {}),
                options=player[config["field"]]["options"],
                distance=player.get("distanceFromTarget", 0),
            )
        else:
            path = root / config["path"]
            entry.update(
                equipment=json.loads(
                    (path / "gear_sets" / f"{config['gear']}.gear.json").read_text()
                ),
                rotation=json.loads(
                    (path / "apls" / f"{config['rotation']}.apl.json").read_text()
                ),
            )
        entry["class_enum"] = "Class" + config["class"].title()
        entry["spec_enum"] = {
            "balance_druid": "SpecBalanceDruid",
            "feral_druid": "SpecFeralCatDruid",
            "beast_mastery_hunter": "SpecHunter",
            "arcane_mage": "SpecMage",
            "retribution_paladin": "SpecRetributionPaladin",
            "shadow_priest": "SpecPriest",
            "rogue": "SpecRogue",
            "elemental_shaman": "SpecElementalShaman",
            "enhancement_shaman": "SpecEnhancementShaman",
            "affliction_warlock": "SpecWarlock",
            "destruction_warlock": "SpecWarlock",
            "fury_warrior": "SpecDpsWarrior",
        }[key]
        manifest["specs"][key] = entry
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, separators=(",", ":")))


if __name__ == "__main__":
    main()
