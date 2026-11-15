<img width="130" height="120" alt="PKLab" src="https://github.com/user-attachments/assets/3f519223-4539-4050-92d5-a4a1bffdd908" />

# PKLab

[English](../README.md) / [Français](README-fr.md) / Español

PKLab es un compañero para los juegos de Pokémon (Gen 2, 3, 4 y 5) jugados en emulador. Lee tu equipo y el del rival en directo desde la memoria del emulador y muestra las debilidades, las estadísticas y los movimientos. También incluye un randomizer, un editor de partidas guardadas y un control deslizante de velocidad del juego.

Descarga: [Releases](https://github.com/mrdbmyla/PKLab/releases) → `PKLab.exe` (no necesita instalación). Las ROM no están incluidas.

## Por qué este código es público

Este repositorio contiene el código fuente exacto con el que se compila `PKLab.exe`. Se publica **solo para que cualquiera pueda comprobar lo que hace el programa** (sin virus, sin recogida de datos, etc.).
**No** es un proyecto de código abierto: todos los derechos reservados (ver [LICENSE](../LICENSE)).

Lo que hace el programa, en resumen:
- servidor local solo en `127.0.0.1:8731` (no accesible desde la red);
- lee la memoria de mGBA / melonDS (`pymem`) para mostrar tu equipo;
- conexiones a Internet (solo descargas, no se envía nada):
  - la API de GitHub de este repositorio, para las actualizaciones (`app/updater.py`); los archivos descargados se comprueban con su sha256;
  - `raw.githubusercontent.com/pret/…`: datos públicos de los mapas (`app/gen3_maps.py`, `app/gen4_maps.py`), guardados en caché;
  - `raw.githubusercontent.com/PokeAPI/sprites`: imágenes de respaldo de los Pokémon;
  - Google Fonts: la fuente de la interfaz;
- sin telemetría, sin cuenta.

## Contenido

| Ruta | Función |
|---|---|
| `app/app.py` | bucle de lectura, servidor HTTP local, ventana (pywebview) |
| `app/nds_reader.py`, `app/games.py` | lectura de los juegos de DS (Gen 4/5) en melonDS |
| `mgba_gen2_bridge.lua` | script que se ejecuta en mGBA para los juegos de GBC (Gen 2: Oro, Plata, Cristal) |
| `mgba_gen3_bridge.lua` | script que se ejecuta en mGBA para los juegos de GBA (Gen 3) |
| `app/engine.py` | decodificación de los Pokémon y cálculo de debilidades |
| `app/randomizer*.py`, `app/save_editor.py`, `app/shiny_patch.py` | herramientas |
| `app/updater.py` | actualizaciones |
| `app/rom_finder.py` | busca las ROM en el PC (solo lee la cabecera de los archivos) |
| `pklab.html`, `data/` | interfaz y datos |
| `app/PKLab.spec` | receta de PyInstaller |

## Compilar el exe uno mismo (para verificar)

Requisitos: Windows, Python 3.11, PyInstaller 6.

```bash
pip install -r app/requirements.txt pyinstaller
```

Los siguientes elementos **no** están en este repositorio y hay que añadirlos a mano antes de compilar:
- `app/mgba_bundle/mGBA.exe`: [mGBA 0.11](https://mgba.io/downloads.html) oficial para Windows (licencia MPL-2.0, [código fuente](https://github.com/mgba-emu/mgba));
- `app/melonds_bundle/melonDS.exe`: [melonDS 1.1](https://melonds.kuribo64.net/downloads.php) oficial para Windows (licencia GPL-3.0, [código fuente](https://github.com/melonDS-emu/melonDS));
- `boxart/` y `data/sprites/`: imágenes de los juegos y de los Pokémon (propiedad de Nintendo / The Pokémon Company, no se redistribuyen aquí).

Después:

```bash
cd app
pyinstaller PKLab.spec --noconfirm
```

El exe se crea en `app/dist/PKLab.exe`.

Los emuladores incluidos en `PKLab.exe` son las versiones oficiales, sin modificar, de los proyectos anteriores; su código fuente está disponible en los enlaces indicados.

## Créditos

Pokémon y todos los nombres relacionados son marcas de Nintendo, Game Freak y The Pokémon Company. PKLab no está afiliado ni respaldado por ellos.
