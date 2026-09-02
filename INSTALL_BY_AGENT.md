# Instalar Pegasus con un agente

Este instructivo es para un agente que instala Pegasus 5 en nombre de una persona, en la cuenta Linux
actual. El agente descarga, verifica y ejecuta cada comando exactamente como está escrito acá; la
persona decide qué MCPs se instalan y mantiene el control de credenciales y modelos.

Pegasus 5 es un solo archivo: `pegasus`. No hay wheel, no hay venv, no hay `pip install` — se
descarga, se verifica y se deja ejecutable en el PATH. Cada paso de esta guía dice si necesita red o
no, y qué hacer si falla.

**Nunca invoques `pegasus` sin subcomando.** Corrido en una terminal abre un menú interactivo (una
TUI) que espera teclas de una persona; un agente no tiene con qué manejarlo. Sin terminal (stdin y
stdout no conectados a una), no hay menú: imprime la misma línea de uso que `--help` y termina con
código de salida distinto de cero -- que tampoco es un resultado útil para vos. Usá siempre un
subcomando explícito (`doctor`, `install`, `uninstall`, `restore`, `models`), y agregá `--json` cuando
necesites un resultado que puedas parsear en vez de prosa.

## 1. Ubicar el checkout y confirmar la cuenta

```sh
test -f pyproject.toml -a -d src/pegasus
id -u
```

Si el segundo comando imprime `0`, detenete: no instales como root. Si el primero falla, no estás en
el checkout de `pegasus-harness` — y no importa: instalar Pegasus no exige ninguno. No le pidas nada a
la persona por esto; seguí directamente con el paso 2 desde el directorio que sea.

## 2. Descargar el asset del release y verificarlo

Sustituí `RELEASE_TAG` por el tag que la persona pidió. Si no nombró ninguno — "instalame pegasus", sin
más — no le preguntes por un número de versión: resolvé vos el último tag publicado, con `gh` si está
disponible y con la API si no.

```sh
gh release view --repo balerdis/pegasus-harness --json tagName -q .tagName

# sin gh:
curl -fsSL https://api.github.com/repos/balerdis/pegasus-harness/releases/latest \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])"
```

Si ninguna de las dos resuelve (sin red, sin `gh`, API caída), no adivines un número: decíselo a la
persona y pedile el tag.

```sh
RELEASE_TAG="v5.9.0"
DOWNLOAD_DIR="$HOME/Downloads/pegasus-$RELEASE_TAG"
mkdir -p "$DOWNLOAD_DIR"
cd "$DOWNLOAD_DIR"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"

curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c pegasus.sha256
python3 -c "
import json, sys
manifest = json.load(open('release-manifest.json'))
assert manifest['schema'] == 'pegasus-harness-release/v5', manifest['schema']
assert manifest['tag'] == '$RELEASE_TAG', manifest['tag']
names = {a['name'] for a in manifest['assets']}
assert names == {'pegasus'}, names
print('release-manifest.json: coincide con', manifest['tag'], manifest['commit'])
"
```

**Detenete y no sigas si:** `sha256sum -c` reporta `FAILED`, o el script de Python levanta
`AssertionError`. Ninguno de los dos casos es recuperable descargando de nuevo del mismo tag: si el
tag ya publicó bytes que no calzan con su propio manifest, avisale a la persona y esperá
instrucciones — no lo instales.

Esta es la única sección de toda la instalación que necesita red: descargar el archivo que se va a
instalar. Pegasus no tiene dependencias de terceros, así que ningún paso posterior vuelve a salir a
internet.

*No ejecutado en esta verificación: `curl` contra GitHub necesita red, prohibida en este entorno de
trabajo. Lo que sí se probó, contra un artefacto construido localmente con `tools/build_zipapp.py` y
su propio `release-manifest.json` generado por `tools/build_release_evidence.py --tag v5.9.0` (el
mismo tag de ejemplo que la sección anterior, para que ambas corridas queden coherentes entre sí), es
que `sha256sum -c` y la comparación de `schema`/`tag`/`assets` distinguen exactamente un archivo
correcto de uno alterado — corrida real:*

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
