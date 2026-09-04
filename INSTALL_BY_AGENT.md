# Instalar Pegasus con un agente

Este instructivo es para un agente que instala Pegasus 5 en nombre de una persona, en la cuenta Linux
actual. El agente descarga, verifica y ejecuta cada comando exactamente como está escrito acá; la
persona decide qué MCPs se instalan y mantiene el control de credenciales y modelos.

Pegasus 5 es un solo archivo: `pegasus`. No hay wheel, no hay venv, no hay `pip install` — se
descarga, se verifica y se deja ejecutable en el PATH. Cada paso de esta guía dice si necesita red o
no, y qué hacer si falla.

**Nunca invoques `pegasus` sin subcomando, bajo ninguna circunstancia.** Corrido en una terminal abre
un menú interactivo (una TUI) que espera teclas de una persona; un agente no tiene con qué manejarlo,
y no hay forma de automatizarlo desde acá -- este instructivo no describe esa interfaz en ningún
momento, a propósito. Sin terminal (stdin y stdout no conectados a una), tampoco hay menú: imprime la
misma línea de uso que `--help` y termina con código de salida distinto de cero, que tampoco es un
resultado útil para vos. Usá siempre un subcomando explícito (`doctor`, `install`, `update`,
`upgrade`, `uninstall`, `restore`, `models`), y agregá `--json` cuando necesites un resultado que
puedas parsear en vez de prosa.

## 0. Usar `install.sh`, cuando alcanza

Si lo único que hace falta es dejar `python3` (ya presente), Node, OpenCode y el binario `pegasus`
instalados -- sin elegir MCPs todavía --, `install.sh` hace eso solo, y es más corto que repetir los
pasos manuales de este documento. La forma no interactiva, la que un agente debe usar, es:

```sh
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh \
  | bash -s -- --yes --no-run
```

`--yes` salta la confirmación (necesaria: nadie va a escribir "y" en un pipe) y `--no-run` evita que
el script lance nada al final -- ni la TUI de Pegasus ni `opencode`, ninguno de los dos es algo que un
agente deba abrir. Repetido sin `--no-run` sí lanzaría uno de los dos según haya instalado algo o no,
así que un agente nunca lo corre sin ese flag. Para inspeccionar qué falta sin cambiar nada -- por
ejemplo, para decidir si hace falta seguir con este instructivo o no --, usá `--verify`:

```sh
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh \
  | bash -s -- --verify
```

`--verify` no descarga nada, no crea directorios, y termina con código de salida distinto de cero si
`python3` está ausente o es más viejo que 3.12 -- el resto de esta guía asume que ese chequeo ya pasó.
Si `install.sh` se niega por ese motivo, no lo resuelvas vos: instalar o actualizar el Python del
sistema es una decisión específica de cada distribución, y una elección equivocada puede romper otra
cosa. Decíselo a la persona con la versión que pide y la que se encontró, tal como el propio script
las imprime, y esperá su decisión.

Lo que `install.sh` no hace es elegir MCPs ni escribirlos en la configuración de OpenCode -- eso sigue
siendo tarea de los pasos de abajo (sección "Instalar en OpenCode y elegir MCPs"), porque es ahí donde
la persona tiene que tomar una decisión explícita por cada servidor.

## 1. Ubicar el checkout y confirmar la cuenta

```sh
test -f pyproject.toml -a -d src/pegasus
id -u
```

Si el segundo comando imprime `0`, detenete: no instales como root. Si el primero falla, no estás en
el checkout de `pegasus-harness` — y no importa: instalar Pegasus no exige ninguno. No le pidas nada a
la persona por esto; seguí directamente con el paso 2 desde el directorio que sea.

## 2. Descargar el asset del release y verificarlo

No hace falta resolver ningún tag ni preguntarle a la persona cuál quiere: `releases/latest/download/`
es un redirect de GitHub que siempre apunta al último release publicado, así que se descarga directo
de ahí.

```sh
DOWNLOAD_DIR="$HOME/Downloads/pegasus"
mkdir -p "$DOWNLOAD_DIR"
cd "$DOWNLOAD_DIR"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/latest/download"

curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c pegasus.sha256
python3 -c "
import json
manifest = json.load(open('release-manifest.json'))
assert manifest['schema'] == 'pegasus-harness-release/v5', manifest['schema']
names = {a['name'] for a in manifest['assets']}
assert names == {'pegasus', 'install.sh'}, names
print('release-manifest.json: coincide con', manifest['tag'], manifest['commit'])
"
```

**Detenete y no sigas si:** `sha256sum -c` reporta `FAILED`, o el script de Python levanta
`AssertionError`. Ninguno de los dos casos es recuperable descargando de nuevo en el momento: si el
release ya publicó bytes que no calzan con su propio manifest, avisale a la persona y esperá
instrucciones — no lo instales. (Un `FAILED` también puede pasar si se publicó un release nuevo justo
entre las dos descargas de arriba; en ese caso, volver a descargar los tres archivos sí resuelve.)

Esta es la única sección de toda la instalación que necesita red: descargar el archivo que se va a
instalar. Pegasus no tiene dependencias de terceros, así que ningún paso posterior vuelve a salir a
internet.

*No ejecutado en esta verificación: `curl` contra GitHub necesita red, prohibida en este entorno de
trabajo. Lo que sí se probó, contra un artefacto construido localmente con `tools/build_zipapp.py` y
su propio `release-manifest.json` generado por `tools/build_release_evidence.py --tag v5.9.0` (un tag
de ejemplo cualquiera, sólo para tener uno en la corrida; no hace falta que coincida con nada de la
sección anterior, que ya no resuelve ningún tag), es que `sha256sum -c` y la comparación de
`schema`/`assets` distinguen exactamente un archivo correcto de uno alterado — corrida real:*

```
$ sha256sum -c pegasus.sha256
pegasus: OK
$ python3 -c "... (script de arriba) ..."
release-manifest.json: coincide con v5.9.0 57d58ccd2d942043a32a20f7696c48fc075e6e5d
```

*y, contra la misma copia con un byte agregado a mano:*

```
$ sha256sum -c pegasus.sha256
pegasus: FAILED
sha256sum: WARNING: 1 computed checksum did NOT match
```

## 3. Dejar el ejecutable en el PATH

```sh
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
install -m 755 pegasus "$BIN_DIR/pegasus"

case ":$PATH:" in
  *":$BIN_DIR:"*) echo "PATH: ya incluye $BIN_DIR" ;;
  *) echo "PATH: falta $BIN_DIR -- invocá el ejecutable por su ruta absoluta y avisale a la persona" ;;
esac
```

**Si falta en el PATH, no lo agregues vos al perfil de shell de nadie**, ni siquiera "temporalmente":
decíselo y seguí. Y no lo necesitás para terminar — tenés la ruta absoluta, así que invocá
`"$BIN_DIR/pegasus"` y andá.

Lo que sí tenés que decirle, con estas palabras, porque es el error fácil de cometer: **un
`source ~/.bashrc` no alcanza.** Quien agrega `~/.local/bin` al PATH suele ser `~/.profile`, que corre
al *iniciar sesión* y no al abrir una terminal, y sólo si el directorio ya existía — y lo acaba de
crear esta instalación. Cerrar sesión y volver a entrar es lo que resuelve. Editar el shell es el
último recurso, no el primero, porque hacerlo cuando no hacía falta deja la entrada duplicada.

*Ejecutado tal cual: `install -m 755` dejó el archivo con permiso `0755`, y el `case` se probó con las
dos ramas (ausente y presente) sobre un `PATH` de prueba.*

## 4. Verificar y reportar

```sh
pegasus doctor
```

Como el paso 2 no depende de red y el paso 3 no toca nada más, si `sha256sum -c` terminó en `0` este
comando ya puede correr. Reporta qué CLIs anfitrionas detecta esta cuenta.

*Ejecutado tal cual, contra el ejecutable puesto en un `bin_dir` de prueba y llamado por PATH:*

```
$ pegasus doctor
OpenCode: present at /home/.config/opencode, Pegasus not installed.
```

## Instalar en OpenCode y elegir MCPs

Con `pegasus` en el PATH, identificá primero el binario de OpenCode en la shell real de la cuenta --
no asumas que una shell de login comparte el mismo PATH que la sesión del agente:

```sh
command -v opencode
```

Pedile a la persona una decisión explícita por cada MCP que quiera instalar; hoy el único servidor
remoto embarcado en el contenido es `context7`. Traducí cada decisión a `--mcp <id>` (instalar) o a la
ausencia del flag (no instalar) -- no hay `--confirm`/`--decline` en v5, un servidor no nombrado
simplemente no se instala:

```sh
pegasus install --cli opencode --dry-run --mcp context7
```

Si la persona ya corre uno de estos servidores por su cuenta bajo una clave propia, no lo instales de
nuevo: usá `--mcp <id>=<clave>` (por ejemplo `--mcp cbm=codebase-memory-mcp`). Esa forma pide a Pegasus
la convención y los permisos del servidor, sin descargar nada ni tocar la configuración de mcp para
ese id -- es lo que corresponde cuando la persona dice "eso ya lo tengo corriendo yo".

**Preflight de Node:** si alguno de los servidores elegidos se distribuye por npm -- hoy, sólo
`playwright` -- e `install` no encuentra `node` en el PATH, se niega antes de escribir nada,
*incluso en `--dry-run`*, con:

```
playwright needs Node to install, and node is not on PATH; installing Node is the user's own
responsibility, so change the selection or make node available before retrying
```

Esto no es un bug ni algo que el agente deba resolver instalando Node por su cuenta: contale a la
persona que ese servidor necesita Node y dale las dos salidas reales -- instalar Node ella misma, o
sacar ese servidor de la selección -- y esperá su decisión. (Reinstalar un servidor npm que ya está
materializado no dispara esto: no hay nada que buscar, así que no hace falta Node.)

Mostrale el plan a la persona antes de aplicar. Recién con su confirmación, repetí el mismo comando sin
`--dry-run`.

## Actualizar una instalación existente

Hay dos comandos que actualizan cosas distintas. No los confundas ni los uses uno por el otro.

### `pegasus update --cli <id>`: reaplica la selección ya instalada

Usalo cuando la persona pide "actualizar" una instalación que ya existe (por ejemplo, después de que
vos mismo la actualizaste con `pegasus upgrade`, o simplemente porque pasó tiempo). **No corras
`pegasus install --cli <id>` a secas para esto:** un `install` sin `--mcp` no nombra ningún servidor, y
un servidor no nombrado se retira -- eso te comería en silencio cualquier atadura de MCP que la
instalación ya tuviera. `update` existe exactamente para evitar ese error: reaplica la selección
propia registrada, MCPs atados incluidos, sin que vos tengas que reconstruirla.

```sh
pegasus update --cli opencode --dry-run --json
```

Mostrale el plan a la persona (o resumíselo) antes de aplicar. Con su confirmación, repetí sin
`--dry-run`:

```sh
pegasus update --cli opencode --json
```

**Si el JSON trae `"status": "failed"`, no reintentes con otros flags -- `update` no tiene ninguno más
que ayude.** Mirá `error` y actuá según cuál de estos dos mensajes es:

- `"opencode has nothing installed to update; run install instead"` -- no hay nada instalado ahí
  todavía. No es un fallo tuyo: contale a la persona que no hay instalación previa para esa CLI y, si
  quiere una, seguí la sección "Instalar en OpenCode y elegir MCPs" de arriba (`install`, no `update`).

- Un mensaje que empieza con `"... has bound mcp server(s) ... whose server key was never recorded"`
  -- `update` se niega a adivinar la clave de un servidor atado que quedó registrado antes de que
  Pegasus la guardara, porque adivinar retiraría justo esa atadura. El mensaje mismo trae, listo para
  copiar, el comando `pegasus install --cli <id> --mcp <id>=<key>` que hace falta correr una vez por
  cada id afectado -- con un `<key>` de relleno en cada uno. **Vos no sabés esa clave.** Conseguila de
  la configuración propia de esa CLI (no es algo que Pegasus guarde) o preguntale a la persona; nunca
  inventes un valor para `<key>`. Corré ese `install` una sola vez con la clave real, y a partir de ahí
  `update` vuelve a funcionar sin flags. `pegasus doctor --json` también imprime este mismo comando,
  bajo `mcp_bound_unknown_keys`, si preferís detectar el caso antes de intentar `update`.

### `pegasus upgrade`: reemplaza el binario de `pegasus`

Esto descarga un ejecutable nuevo y lo instala en lugar del actual. **Nunca lo corras por tu cuenta:**
necesitás el visto bueno explícito de la persona antes de ejecutarlo sin `--dry-run`, igual que con
cualquier escritura sobre su cuenta. Empezá siempre por el `--dry-run`:

```sh
pegasus upgrade --dry-run --json
```

Si el plan muestra una versión nueva y la persona confirma, corré el upgrade real y **reportá el
resultado de la verificación, no solo "listo"**:

```sh
pegasus upgrade --json
```

Con éxito, el JSON trae `"status": "upgraded"`, `"old_version"`, `"new_version"` y
`"restart_required": true`. Ese último campo no es adorno: **el proceso de `pegasus` que hizo el
upgrade sigue siendo la versión vieja** -- conserva el inode del archivo con el que arrancó. No le
digas a la persona que la versión nueva ya está activa, ni la asumas vos mismo en el siguiente comando
que corras: decile explícitamente que tiene que reiniciar Pegasus (cerrar y volver a invocarlo) para
que la versión nueva quede en efecto.

Si el JSON trae `"status": "already-current"`, tampoco es un error -- el código de salida es `0`
igual que con `"upgraded"`. Significa que ya estaba en la versión más nueva publicada (viene en
`"version"`); decíselo a la persona tal cual, sin reintentar nada ni tratarlo como una falla.

Si el JSON trae `"status": "failed"` (código de salida distinto de cero), mirá `error` -- no hay flag
que arregle ninguno de estos:

- `"could not reach GitHub to check the newest published release -- ..."` -- no hay red. No reintentes
  en loop; avisá y esperá a que haya conexión.
- `"... is not writable by this process; upgrade refuses to download anything it could not then
  install. Instead, ..."` -- el mensaje mismo trae el comando manual (descargar, verificar contra
  `pegasus.sha256`, y copiar el archivo a mano, con `root`/`sudo` si hace falta). No intentes escalar
  privilegios vos mismo; pasale ese comando a la persona.
- `"pegasus is not running from an installed executable -- ..."` -- estás corriendo desde un checkout
  de código fuente, no desde el zipapp del release. No hay binario que reemplazar acá; si la persona
  quiere el ejecutable, seguí la sección de instalación de este mismo instructivo en la cuenta
  correspondiente.

## Respetar el estado existente

No fuerces colisiones: Pegasus las informa y preserva los archivos o claves existentes. Después de
instalar, revisá `pegasus doctor` y el journal en
`$XDG_DATA_HOME/pegasus-harness/journal-v4.json` (o `~/.local/share/pegasus-harness/journal-v4.json`
si esa variable no está definida). La persona puede usar las herramientas de OpenCode que elija para su
propia configuración, pero el agente no debe pedir, leer ni reproducir su contenido.

Si hace falta deshacer algo, usá únicamente `pegasus restore` (vuelve a la generación anterior) o
`pegasus uninstall --cli opencode` (retira sólo lo que el journal reclama como propio). No borres
configuración ajena a mano.

La instalación manual canónica está en [INSTALL.md](INSTALL.md); [README.md](README.md) presenta
ambas rutas y [MANUAL.md](MANUAL.md) explica el control de modelo y proveedor de la persona.
