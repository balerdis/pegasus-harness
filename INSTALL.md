# Instalar Pegasus

Pegasus soporta hoy Linux, con dos clientes: OpenCode y Claude Code. Ejecutá esto:

```sh
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash
```

Ese único comando detecta qué te falta, te muestra el plan completo antes de tocar nada, pide
confirmación, instala sólo lo que hace falta, y termina dejándote siempre en la interfaz de Pegasus:
si instaló algo nuevo, bajo OpenCode todavía hay que elegir MCPs y confirmar dentro de esa interfaz;
bajo Claude Code no hace falta ningún reinicio, la configuración se lee tal como quedó escrita. Si tu
entorno ya estaba completo, se abre igual para avisarte si hay una versión más nueva de pegasus
publicada. No hace falta elegir una versión ni copiar un tag a mano: siempre baja el último release
publicado.

El script nunca elige el CLI por su cuenta. Con `--cli claudecode` o `--cli opencode` instala en ese
uno sin preguntar. Sin el flag, hay tres casos: si la cuenta tiene exactamente uno de los dos ya
instalado, el preflight lo nombra como destino y la misma confirmación de siempre lo cubre; si no hay
ninguno instalado, o hay más de uno, y hay una terminal, te pregunta cuál elegir; sin terminal (por
ejemplo, `curl | bash` corrido por un proceso sin tty) y sin `--cli`, el script falla nombrando el
flag y los ids válidos, en vez de elegir uno por su cuenta.

El resto de esta guía explica, en orden, qué hace exactamente ese script, y qué hace falta para
mantener la instalación al día o deshacerla. Para usar Pegasus una vez instalado — la interfaz
interactiva (TUI) y la línea de comandos completa — consultá [MANUAL.md](MANUAL.md) si tu CLI es
OpenCode, o [MANUAL-claude-code.md](MANUAL-claude-code.md) si es Claude Code.

*(`install.sh` sólo está pensado para Linux: sus pistas de Python son `apt`/`dnf`, propias de esa
familia de sistemas. No decimos nada sobre macOS acá — ni que funciona ni que falla — porque no lo
probamos.)*

## 1. Qué hace `install.sh`

**Detecta, sin instalar nada todavía:** si tenés `python3` 3.12 o más nuevo (lo que pide
`pyproject.toml`), `curl`, `node`, cada uno de los dos CLIs soportados (`opencode` y `claude`, los dos,
no sólo el elegido con `--cli`), un `pegasus` ya instalado, y si el directorio de destino del binario
ya está en tu `PATH`.

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
lo que ya está): nvm y Node LTS -- incondicional, para cualquiera de los dos CLIs, porque parte de los
MCPs que Pegasus distribuye se materializa con npm sea cual sea el destino --, después el CLI elegido
con su propio instalador oficial (`opencode.ai/install` para OpenCode, `claude.ai/install.sh` para
Claude Code -- ninguno de los dos es cosa de `pegasus`, sólo de este script), y por último el binario
`pegasus`, verificado contra su checksum antes de instalarse. Sólo OpenCode fija una versión (por la
misma razón que fija la de nvm: la API de GitHub sin autenticar permite 60 pedidos por hora por IP, y
resolver "la última versión" cada vez la agota rápido); el instalador oficial de Claude Code no toma
ese parámetro. Si el checksum del binario de `pegasus` no coincide, el script se detiene y no instala
nada; eso también puede pasar si se publicó un release nuevo entre las dos descargas, así que lo
primero que vale la pena probar es correr el script de nuevo. Si ya había un `pegasus` instalado, no
lo pisa: te dice qué versión encontró y que `pegasus upgrade` es el comando que reemplaza el binario
(se explica en [MANUAL.md](MANUAL.md#mantener-pegasus-al-día)).

**Flags:**

| Flag | Qué hace |
| --- | --- |
| (ninguno) | detecta, muestra el plan, pide confirmación, instala lo que falte |
| `--cli ID` | elige qué CLI instalar sin preguntar (`claudecode` u `opencode`). Sin este flag: si hay exactamente un CLI ya instalado, ese es el destino; si hay ambigüedad y una terminal, se pregunta cuál; sin terminal, el script falla nombrando este flag |
| `--verify` | informa el estado; no cambia nada — ni descarga, ni crea directorios |
| `--yes`, `-y` | salta la confirmación |
| `--no-run` | instala lo que falte igual que una corrida normal, pero no lanza nada al final: imprime qué habría lanzado |
| `--bin-dir DIR` | instala el binario de `pegasus` en `DIR` en vez de `~/.local/bin` |
| `--opencode-version X` | si el CLI elegido es OpenCode, fija la versión a instalar |
| `--opencode-ultima` | si el CLI elegido es OpenCode, instala la última versión publicada (consulta la API de GitHub) |
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

**Qué queda corriendo al final:** siempre la interfaz de Pegasus (ver
[Usar la interfaz interactiva de Pegasus](MANUAL.md#usar-la-interfaz-interactiva-de-pegasus-la-tui) en
el manual). Si instaló algo nuevo y el CLI elegido fue OpenCode, porque todavía falta elegir qué MCPs
instalar y confirmar esa instalación ahí; si fue Claude Code, no hace falta ningún paso de activación
adicional, pero la TUI de Pegasus sigue siendo el lugar donde se elige qué MCPs instalar la primera
vez. Si no hacía falta instalar nada, porque `install.sh` no compara versiones — sólo dice si algo
está o no está — y es la TUI, al arrancar, la que revisa si hay un release de pegasus más nuevo
publicado y te ofrece `Upgrade`. Bajo `--verify` o `--no-run` no lanza nada: dice qué habría lanzado.

## 2. Mantener la instalación al día

Una vez instalado, usar Pegasus día a día — la TUI o la línea de comandos completa, con todos sus
flags — está en [MANUAL.md](MANUAL.md). Esta sección cubre sólo lo que hace falta para no perder una
selección ya registrada al reinstalar, y dónde seguir para actualizar el binario o revisar el estado.

**Actualizar una instalación ya hecha.** `pegasus update --cli <id>` reaplica la selección que esa
instalación ya tiene registrada — MCPs atados incluidos — sin que haga falta repetir ningún flag. Esto
existe porque un `install` a secas, sin `--mcp`, no nombra ningún servidor: sobre una instalación que
ya tiene una selección registrada se **rechaza** antes de escribir nada, en vez de retirarla en
silencio porque nadie repitió el flag. `update` es la forma de traer la instalación al día dejando esa
selección como está, y `--mcp none` la de revocarla a propósito. Las tres cosas —el rechazo, que
`update` no toque la selección, y que la revocación deliberada la vacíe de verdad— las corre contra
una instalación real `InstallGuidesSayABareInstallIsRefusedTest`
(`tests/test_install_guides_command_surface.py`):

```sh
pegasus update --cli opencode --dry-run
pegasus update --cli opencode
```

Para actualizar el binario en sí (`pegasus upgrade`, que no toca ninguna instalación puntual) y para
verificar el estado (`pegasus doctor`), ver
[Mantener Pegasus al día](MANUAL.md#mantener-pegasus-al-día) y
[Verificar el estado](MANUAL.md#verificar-el-estado) en el manual.

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
| El CLI anfitrión (OpenCode o Claude Code) | Usted lo instala, actualiza y configura. Pegasus no lo hace por usted -- `install.sh` de la sección anterior es la única excepción, y sólo para dejarlo presente antes de que `pegasus` entre en escena. |
| Archivos y claves de configuración existentes | Se detectan y se preservan. Una colisión se informa; no se sobreescribe. |
| MCPs opcionales | `pegasus install --cli <id> --mcp <id-del-mcp>` decide qué servidores se instalan; uno no nombrado no se descarga, configura ni registra. También acepta `--mcp <id-del-mcp>=<clave>`. |
| Credenciales, proveedores y modelos | Nunca se distribuyen ni se imponen acá. Esa configuración es de cada CLI (bajo OpenCode, `/connect` para las credenciales y `/models` para el modelo). Aparte, Pegasus tiene su propia asignación de modelo por agente (`pegasus models set`), y sólo OpenCode la soporta hoy -- Claude Code no tiene un catálogo de modelos en disco que Pegasus pueda leer, así que su adapter no declara esa capacidad, y los tres subcomandos de `models` (`set`, `unset`, `list`) se niegan a correr contra `--cli claudecode`, nombrando el CLI y explicando por qué. |
| Rollback | `pegasus restore` devuelve el estado exacto anterior al último comando; `pegasus uninstall --cli <id>` retira sólo lo que el journal reclama como propio. |
| Actualizaciones | `pegasus update --cli <id>` reaplica la selección ya instalada. `pegasus upgrade` reemplaza el binario de `pegasus`. Son cosas distintas — ver [Mantener Pegasus al día](MANUAL.md#mantener-pegasus-al-día) en el manual. |

Si alguno de los servidores elegidos se distribuye por npm (hoy, sólo `playwright`) y no hay `node` en
el PATH, `install` se niega antes de escribir nada — también en `--dry-run` — con:

```
playwright needs Node to install, and node is not on PATH; installing Node is the user's own
responsibility, so change the selection or make node available before retrying
```

Esa tabla dice qué se preserva; lo que no, está en
[Limitaciones aceptadas](docs/arquitectura/arquitectura.md#limitaciones-aceptadas): un archivo que
Pegasus instaló y vos editaste después se reescribe y se borra como cualquier otro, y ahí está el
motivo, el alcance del aviso `overwritten` y la ventana de recuperación de `pegasus restore`.

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para la política de ownership y rollback, consultá
[docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md). Si un agente te asiste, usá
[INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) antes de recibir comandos de instalación.
