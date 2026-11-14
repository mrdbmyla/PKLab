<img width="130" height="120" alt="PKLab" src="https://github.com/user-attachments/assets/3f519223-4539-4050-92d5-a4a1bffdd908" />

# PKLab

English / [Français](.github/README-fr.md) / [Español](.github/README-es.md)

PKLab is a companion app for Pokémon games (Gen 3, 4 and 5) played on an emulator. It reads your party and the opponent live from the emulator's memory and shows weaknesses, stats and moves. It also includes a randomizer, a save editor and a game speed slider.

Download: [Releases](https://github.com/mrdbmyla/PKLab/releases) → `PKLab.exe` (no installation needed). ROMs are not included.

## Why this code is public

This repository contains the exact source code used to build `PKLab.exe`. It is published **only so that anyone can check what the program does** (no malware, no data collection, etc.).
This is **not** an open source project: all rights are reserved (see [LICENSE](LICENSE)).

What the program does, in short:
- local server on `127.0.0.1:8731` only (not reachable from the network);
- reads the memory of mGBA / melonDS (`pymem`) to show your party;
- Internet connections (downloads only, nothing is sent):
  - this repository's GitHub API, for updates (`app/updater.py`); downloaded files are checked by their sha256;
  - `raw.githubusercontent.com/pret/…`: public map data (`app/gen3_maps.py`, `app/gen4_maps.py`), cached locally;
  - `raw.githubusercontent.com/PokeAPI/sprites`: fallback Pokémon images;
  - Google Fonts: the interface font;
- no telemetry, no account.

## Contents

| Path | Role |
|---|---|
| `app/app.py` | read loop, local HTTP server, window (pywebview) |
| `app/nds_reader.py`, `app/games.py` | reading DS games (Gen 4/5) in melonDS |
| `mgba_gen3_bridge.lua` | script run inside mGBA for GBA games (Gen 3) |
| `app/engine.py` | Pokémon decoding and weakness calculation |
| `app/randomizer*.py`, `app/save_editor.py`, `app/shiny_patch.py` | tools |
| `app/updater.py` | updates |
| `app/rom_finder.py` | finds ROMs on the PC (reads only the file header) |
| `pklab.html`, `data/` | interface and data |
| `app/PKLab.spec` | PyInstaller recipe |

## Building the exe yourself (for verification)

Requirements: Windows, Python 3.11, PyInstaller 6.

```bash
pip install -r app/requirements.txt pyinstaller
```

The following are **not** in this repository and must be added by hand before building:
- `app/mgba_bundle/mGBA.exe`: official [mGBA 0.11](https://mgba.io/downloads.html) for Windows (MPL-2.0 license, [source code](https://github.com/mgba-emu/mgba));
- `app/melonds_bundle/melonDS.exe`: official [melonDS 1.1](https://melonds.kuribo64.net/downloads.php) for Windows (GPL-3.0 license, [source code](https://github.com/melonDS-emu/melonDS));
- `boxart/` and `data/sprites/`: game and Pokémon images (property of Nintendo / The Pokémon Company, not redistributed here).

Then:

```bash
cd app
pyinstaller PKLab.spec --noconfirm
```

The exe is created in `app/dist/PKLab.exe`.

The emulators shipped inside `PKLab.exe` are the official, unmodified releases of the projects above; their source code is available at the links given.

## Credits

Pokémon and all related names are trademarks of Nintendo, Game Freak and The Pokémon Company. PKLab is not affiliated with or endorsed by them.
