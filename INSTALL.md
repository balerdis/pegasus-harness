# Instalar Pegasus

Pegasus soporta hoy Linux, con OpenCode como único cliente. Ejecutá esto:

```sh
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash
```

Ese único comando detecta qué te falta, te muestra el plan completo antes de tocar nada, pide
confirmación, instala sólo lo que hace falta, y termina dejándote en el lugar que corresponde: la
interfaz de Pegasus si instaló algo nuevo, o `opencode` directo si tu entorno ya estaba completo. No
hace falta elegir una versión ni copiar un tag a mano: siempre baja el último release publicado.

El resto de esta guía explica, en orden, qué hace exactamente ese script, qué significa usar la
interfaz interactiva de Pegasus una vez instalado, y qué significa usarlo por línea de comandos —
para cuando alguna de esas dos formas de operarlo te convenga más que la que uses por default.

*(`install.sh` sólo está pensado para Linux: sus pistas de Python son `apt`/`dnf`, propias de esa
familia de sistemas. No decimos nada sobre macOS acá — ni que funciona ni que falla — porque no lo
probamos.)*

## 1. Qué hace `install.sh`

**Detecta, sin instalar nada todavía:** si tenés `python3` 3.12 o más nuevo (lo que pide
`pyproject.toml`), `curl`, `node`, `opencode`, un `pegasus` ya instalado, y si el directorio de
destino del binario ya está en tu `PATH`.

**Te muestra el plan antes de escribir nada:** un bloque con cada requisito y su estado — presente
(con versión), o "se instalará" (con qué exactamente, versión pinneada incluida). Es la pantalla que
existe para que veas la lista completa de lo que va a pasar antes de que pase.

**Se niega a adivinar dos cosas, y por qué:**

- Un `python3` ausente o más viejo que 3.12: instalar o actualizar el Python del sistema es una
  decisión específica de cada distribución, y equivocarla puede romper otras cosas que dependen de
  ese mismo intérprete. El script se detiene, nombra la versión que hace falta y la que encontró, y
  te deja como pista (sin ejecutarla él mismo) el comando típico de cada familia:
  `sudo apt install python3` en Debian/Ubuntu, `sudo dnf install python3` en Fedora/RHEL.
- Un `curl` ausente: sin él no hay forma de bajar nada de lo que sigue, así que tampoco lo instala
  por vos.

Si falta cualquiera de las dos, el script termina con una explicación y no llega a pedir
confirmación. Si no falta nada de eso, sigue: te muestra el plan y, salvo `--yes`, pregunta antes de
instalar.

**Se niega a correr como root.** Un proceso con `EUID` 0 dejaría archivos con dueño `root` adentro de
un home que no es de `root`, y eso rompe la cuenta en silencio. Si querés probarlo en una cuenta
separada de la tuya, la forma correcta es abrir sesión en esa cuenta primero y recién ahí correr el
script sin `sudo`:

```sh
sudo -u <usuario> -i
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash
```

nunca `sudo ./install.sh`.

**Instala, en orden de dependencia, sólo lo que falta** (y correrlo dos veces es seguro: no reinstala
lo que ya está): nvm y Node LTS, después OpenCode con una versión fija (por la misma razón que fija la
versión de OpenCode: la API de GitHub sin autenticar permite 60 pedidos por hora por IP, y resolver
"la última versión" cada vez la agota rápido), y por último el binario `pegasus`, verificado contra su
checksum antes de instalarse — si el checksum no coincide, el script se detiene y no instala nada; eso
también puede pasar si se publicó un release nuevo entre las dos descargas, así que lo primero que
vale la pena probar es correr el script de nuevo. Si ya había un `pegasus` instalado, no lo pisa: te
dice qué versión encontró y que `pegasus upgrade` es el comando que reemplaza el binario (se explica
en la sección 3).

**Flags:**

| Flag | Qué hace |
| --- | --- |
| (ninguno) | detecta, muestra el plan, pide confirmación, instala lo que falte |
| `--verify` | informa el estado; no cambia nada — ni descarga, ni crea directorios |
| `--yes`, `-y` | salta la confirmación |
| `--no-run` | instala lo que falte igual que una corrida normal, pero no lanza nada al final: imprime qué habría lanzado |
| `--bin-dir DIR` | instala el binario de `pegasus` en `DIR` en vez de `~/.local/bin` |
| `--opencode-version X` | fija la versión de OpenCode a instalar |
| `--opencode-ultima` | instala la última versión de OpenCode publicada (consulta la API de GitHub) |
| `--help`, `-h` | imprime el uso |

**Detecta tu shell y, si hace falta, deja el PATH resuelto para las próximas terminales.** Bajo
bash/sh en Debian/Ubuntu, con el destino de siempre (`~/.local/bin`), no hace falta tocar nada:
`~/.profile` ya se encarga. En cualquier otro caso — zsh, fish, o un `--bin-dir` distinto del de
siempre — el script agrega la línea de PATH que corresponda al archivo de configuración real de tu
shell (`~/.zshrc`, `~/.config/fish/config.fish`, etc., siguiendo el mismo criterio que usa el
instalador oficial de OpenCode para elegir ese archivo), de forma idempotente: si esa línea, EXACTA,
ya está en el archivo, no se agrega una copia de más. Si el archivo no se puede escribir (permisos,
o un symlink que apunta fuera de `$HOME` o a algo que no es tuyo), no aborta la instalación: avisa y
te muestra la línea exacta para que la agregues vos a mano, además del `export PATH=...` para la
terminal actual. Al final igual te muestra, explícito, el comando `source` que necesitás correr en
la terminal actual para no tener que abrir una nueva.

**Qué queda corriendo al final:** si instaló algo nuevo, lanza la interfaz de Pegasus (sección 2) —
porque todavía falta elegir qué MCPs instalar y confirmar esa instalación en OpenCode. Si no hacía
falta instalar nada, lanza `opencode` directo — un entorno completo es, sencillamente, uno donde ya se
puede trabajar. Bajo `--verify` o `--no-run` no lanza ninguno de los dos: dice cuál habría sido.

## 2. Usar la interfaz interactiva de Pegasus (la TUI)

Correr `pegasus` sin ningún subcomando, en una terminal, abre un menú — no imprime ayuda ni corre
nada por sí solo. Es el camino pensado para una persona que está preparando su propia máquina y quiere
ver qué va a pasar antes de que pase: cada pantalla de selección va seguida de una vista previa del
plan, y recién al confirmar esa vista previa se escribe algo de verdad. Nada se instala por elegirlo
en el menú; se instala al confirmar la pantalla de resultado de esa elección.

El menú principal agrupa sus siete entradas por intención, y el orden es a propósito: `Install`,
`Update` y `Upgrade` primero (instalar y mantenerse al día), después `Configure models`, después
`Status and diagnostics`, y por último `Uninstall` antes de `Exit` — la entrada destructiva queda
lejos de donde la navegación con flechas la podría tocar por accidente.

Se maneja enteramente con el teclado: flechas o `j`/`k` para moverte, `enter` o `espacio` para elegir
(en la pantalla de selección de MCPs, cualquiera de los dos tilda o destilda un servidor), `d` para
borrar donde aplica, `esc` para volver a la pantalla anterior, `q` para salir. Si corrés `pegasus` sin
una terminal atrás (salida redirigida a un archivo o a una tubería), no hay menú que mostrar: imprime
la misma línea de uso que `pegasus --help` y termina con código de salida distinto de cero — por eso
un agente nunca debería invocarlo así (ver [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md)).

Al abrir el menú pueden aparecer, arriba de todo, hasta dos avisos independientes — separados a
propósito, porque cada uno se arregla distinto: uno local (esta instalación se hizo con una versión de
Pegasus más vieja que la que estás corriendo ahora → `Update`), y uno remoto (hay un release más nuevo
publicado que el binario que estás corriendo → `Upgrade`). El chequeo remoto corre en segundo plano,
no bloquea el menú, y falla en silencio ante cualquier problema de red.

Durante una instalación, la TUI muestra una barra de progreso con la unidad que se está procesando; al
terminar con éxito, la pantalla de resultado remata con un banner "PEGASUS HARNESS". Por debajo es la
misma instalación de siempre — llama al mismo motor que la sección siguiente — así que nada de lo que
sigue deja de aplicar si preferís este camino.

## 3. Usar `pegasus` por línea de comandos

Esta es la vía no interactiva: cada comando toma flags explícitas, no hay menú ni pantalla de espera,
`--dry-run` te muestra el plan sin escribir nada, `--json` te da un reporte que podés parsear en vez de
prosa, y el código de salida es el contrato — `0` para éxito, distinto de cero para cualquier otra
cosa. Es la forma pensada para scripts, para reproducir la misma instalación en varias máquinas, y para
cualquiera que prefiera no abrir un menú.

**Instalar y elegir MCPs.** Un servidor no nombrado no se instala; no hay `--confirm`/`--decline`:

```sh
pegasus install --cli opencode --dry-run --mcp context7
pegasus install --cli opencode --mcp context7
```

Si ya administrás vos mismo alguno de esos servidores bajo una clave propia, `--mcp <id>=<clave>` ata
la convención y los permisos a esa clave existente, sin descargar ni configurar nada para ese id (por
ejemplo `--mcp cbm=codebase-memory-mcp`).

**Actualizar una instalación ya hecha.** `pegasus update --cli <id>` reaplica la selección que esa
instalación ya tiene registrada — MCPs atados incluidos — sin que haga falta repetir ningún flag. Esto
existe porque un `install` a secas, sin `--mcp`, no nombra ningún servidor y por lo tanto **retira**
los que ya estaban atados; `update` es la forma de traer la instalación al día sin ese riesgo:

```sh
pegasus update --cli opencode --dry-run
pegasus update --cli opencode
```

**Actualizar el programa en sí.** `pegasus upgrade` descarga el `pegasus` más nuevo publicado, lo
verifica contra su `pegasus.sha256`, y reemplaza el binario en ejecución con un único rename atómico.
No lleva `--cli`: no se trata de ninguna instalación puntual.

```sh
pegasus upgrade --dry-run
pegasus upgrade
```

Después hace falta reiniciar Pegasus: el proceso que acaba de hacer el upgrade sigue siendo, en
memoria, la versión vieja — conserva el inode del archivo con el que arrancó.

**Ver el estado.** `pegasus doctor` (con `--json` para la forma parseable) reporta qué CLIs anfitrionas
detecta y qué tiene instalado cada una.

```sh
pegasus doctor --json
```

Para el detalle completo de cada comando — mensajes de error exactos, la lógica de `restore` y
`uninstall`, el preflight de Node para servidores npm — consultá [MANUAL.md](MANUAL.md).

## Instalación manual (sin el script)

Si preferís no correr `install.sh` — por ejemplo, para revisar cada paso vos mismo — podés hacer lo
mismo a mano. No hace falta nombrar ningún tag: `releases/latest/download/` siempre resuelve al
último release publicado.

```sh
mkdir -p "$HOME/Downloads/pegasus"
cd "$HOME/Downloads/pegasus"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/latest/download"

curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c pegasus.sha256
```

`pegasus.sha256` alcanza para verificar los bytes; `release-manifest.json` además ata ese archivo al
commit exacto que lo produjo (`tag`, `commit`, `package_version`). Si `sha256sum -c` falla, no sigas:
no tenés lo que el release publicó — esto también puede pasar si se publicó un release nuevo entre las
dos descargas, así que repetir la descarga es lo primero que vale la pena probar.

```sh
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
install -m 755 pegasus "$BIN_DIR/pegasus"

case ":$PATH:" in
  *":$BIN_DIR:"*)
    echo "listo: $BIN_DIR ya está en tu PATH" ;;
  *)
    echo "$BIN_DIR todavía no está en tu PATH."
    echo "Para usarlo ahora mismo, en esta terminal:   export PATH=\"$BIN_DIR:\$PATH\""
    echo "Para que quede: cerrá la sesión y volvé a entrar. La mayoría de los sistemas"
    echo "agregan ese directorio al iniciar sesión, pero sólo si ya existía — y lo acabás"
    echo "de crear. Editá tu shell sólo si después de volver a entrar sigue sin aparecer."
    ;;
esac
```

`pegasus` es el único archivo que hace falta: no busca un venv y no depende de nada instalado antes
que él.

**Un `source ~/.bashrc` no alcanza**, y es el error fácil de cometer: quien agrega `~/.local/bin` al
PATH suele ser `~/.profile`, que corre al *iniciar sesión* y no al abrir una terminal. Si volvés a
entrar y `pegasus` sigue sin aparecer, ahí sí editá tu shell.

Con eso ya podés confirmar la instalación:

```sh
pegasus doctor
```

### Si venís de una instalación 4.x

Pegasus 4.x dejaba un shim en `~/.local/bin/pegasus` que arrancaba un venv privado propio, en
`~/.local/share/pegasus-harness/venv` (o `$XDG_DATA_HOME/pegasus-harness/venv` si esa variable estaba
definida). El `install -m 755` de arriba pisa ese shim con el archivo único de la serie 5.x — eso ya
está comprobado y es lo esperado. Lo que no toca es ese venv viejo: queda en disco, sin nada que lo
use. Ese directorio es distinto del que guarda el journal y los snapshots
(`~/.local/share/pegasus-harness/` sin el `venv` al final), así que borrarlo no toca tu historial de
instalación ni tu capacidad de hacer `pegasus restore`:

```sh
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/pegasus-harness/venv"
```

### Si sólo hay `python` (no `python3`) en el PATH

`pegasus` arranca con `#!/usr/bin/env python3`, así que si tu sistema sólo tiene `python` en el PATH
vas a ver `/usr/bin/env: 'python3': No such file or directory`, código de salida 127. Comprobá con
`python --version` que sea 3.12 o más nuevo y, si lo es, corré el archivo pasándoselo como argumento en
vez de ejecutarlo directo:

```sh
python "$BIN_DIR/pegasus" doctor
```

## Lo que sigue bajo su control

| Tema | Cómo trabaja Pegasus |
| --- | --- |
| OpenCode | Usted instala, actualiza y configura el cliente anfitrión. Pegasus no lo hace por usted. |
| Archivos y claves de configuración existentes | Se detectan y se preservan. Una colisión se informa; no se sobreescribe. |
| MCPs opcionales | `pegasus install --cli opencode --mcp <id>` decide qué servidores se instalan; uno no nombrado no se descarga, configura ni registra. También acepta `--mcp <id>=<clave>`. |
| Credenciales, proveedores y modelos | Nunca se distribuyen ni se imponen acá. La persona configura las credenciales del proveedor con `/connect` y selecciona el modelo con `/models`, dentro de OpenCode. |
| Rollback | `pegasus restore` devuelve el estado exacto anterior al último comando; `pegasus uninstall --cli opencode` retira sólo lo que el journal reclama como propio. |
| Actualizaciones | `pegasus update --cli opencode` reaplica la selección ya instalada. `pegasus upgrade` reemplaza el binario de `pegasus`. Son cosas distintas — ver la sección 3 más arriba. |

Si alguno de los servidores elegidos se distribuye por npm (hoy, sólo `playwright`) y no hay `node` en
el PATH, `install` se niega antes de escribir nada — también en `--dry-run` — con:

```
playwright needs Node to install, and node is not on PATH; installing Node is the user's own
responsibility, so change the selection or make node available before retrying
```

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para la política de ownership y rollback, consultá
[docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md). Si un agente te asiste, usá
[INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) antes de recibir comandos de instalación.
