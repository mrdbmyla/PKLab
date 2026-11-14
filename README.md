# PKLab

PKLab est un compagnon pour les jeux Pokémon (Gen 3, 4 et 5) joués sur émulateur : il lit l'équipe et l'adversaire en direct dans la mémoire de l'émulateur et affiche les faiblesses, les stats et les attaques. Il inclut aussi un randomizer, un éditeur de sauvegarde et un réglage de la vitesse du jeu.

Téléchargement : [Releases](https://github.com/mrdbmyla/PKLab/releases) → `PKLab.exe` (aucune installation). Les ROM ne sont pas fournies.

## Pourquoi ce code est public

Ce dépôt contient le code source exact qui sert à construire `PKLab.exe`. Il est publié **uniquement pour que chacun puisse vérifier ce que fait le programme** (absence de virus, de collecte de données, etc.).
Ce n'est **pas** un projet open source : tous les droits sont réservés (voir [LICENSE](LICENSE)).

Ce que fait le programme, en bref :
- serveur local sur `127.0.0.1:8731` uniquement (aucun accès depuis le réseau) ;
- lecture de la mémoire de mGBA / melonDS (`pymem`) pour afficher l'équipe ;
- connexions Internet (téléchargements seulement, rien n'est envoyé) :
  - API GitHub de ce dépôt pour les mises à jour (`app/updater.py`), fichiers vérifiés par leur sha256 ;
  - `raw.githubusercontent.com/pret/…` : données publiques des cartes (`app/gen3_maps.py`, `app/gen4_maps.py`), mises en cache ;
  - `raw.githubusercontent.com/PokeAPI/sprites` : images de secours des Pokémon ;
  - Google Fonts : police de l'interface ;
- aucune télémétrie, aucun compte.

## Contenu

| Chemin | Rôle |
|---|---|
| `app/app.py` | boucle de lecture, serveur HTTP local, fenêtre (pywebview) |
| `app/nds_reader.py`, `app/games.py` | lecture des jeux DS (Gen 4/5) dans melonDS |
| `mgba_gen3_bridge.lua` | script lancé dans mGBA pour les jeux GBA (Gen 3) |
| `app/engine.py` | décodage des Pokémon et calcul des faiblesses |
| `app/randomizer*.py`, `app/save_editor.py`, `app/shiny_patch.py` | outils |
| `app/updater.py` | mises à jour |
| `pklab.html`, `data/` | interface et données |
| `app/PKLab.spec` | recette PyInstaller |

## Construire l'exe soi-même (vérification)

Prérequis : Windows, Python 3.11, PyInstaller 6.

```bash
pip install -r app/requirements.txt pyinstaller
```

Les éléments suivants ne sont **pas** dans ce dépôt et doivent être ajoutés à la main avant la construction :
- `app/mgba_bundle/mGBA.exe` : [mGBA 0.11](https://mgba.io/downloads.html) officiel pour Windows (licence MPL-2.0, [code source](https://github.com/mgba-emu/mgba)) ;
- `app/melonds_bundle/melonDS.exe` : [melonDS 1.1](https://melonds.kuribo64.net/downloads.php) officiel pour Windows (licence GPL-3.0, [code source](https://github.com/melonDS-emu/melonDS)) ;
- `boxart/` et `data/sprites/` : images des jeux et des Pokémon (propriété de Nintendo / The Pokémon Company, non redistribuées ici).

Puis :

```bash
cd app
pyinstaller PKLab.spec --noconfirm
```

L'exe est créé dans `app/dist/PKLab.exe`.

Les émulateurs fournis dans `PKLab.exe` sont les versions officielles, non modifiées, des projets ci-dessus ; leur code source est disponible aux liens indiqués.

## Mentions

Pokémon et tous les noms associés sont des marques de Nintendo, Game Freak et The Pokémon Company. PKLab n'est ni affilié ni approuvé par eux.

---

## English

PKLab is a companion app for Pokémon games (Gen 3–5) played on an emulator: it reads your party and the opponent live from emulator memory and shows weaknesses, stats and moves.

This repository holds the exact source code used to build `PKLab.exe`. It is public **only so anyone can check what the program does**. It is **not** open source: all rights are reserved (see [LICENSE](LICENSE)). The emulators (mGBA, MPL-2.0; melonDS, GPL-3.0), game box art, sprites and ROMs are not included.
