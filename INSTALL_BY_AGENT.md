# Instalar Pegasus con un agente

Este instructivo es para un agente que instala Pegasus 4 en nombre de una persona, en la cuenta Linux
actual. El agente descarga, verifica y ejecuta cada comando exactamente como está escrito acá; la
persona decide qué MCPs se instalan y mantiene el control de credenciales y modelos.

No hay `install.sh` ni tarball en v4: Pegasus se instala como un paquete de Python dentro de un venv
privado, y después se deja un lanzador (`pegasus`) en el PATH. Cada paso de esta guía dice si necesita
red o no, y qué hacer si falla.

## 1. Ubicar el checkout y confirmar la cuenta

```sh
test -f pyproject.toml -a -d src/pegasus
id -u
```

Si el segundo comando imprime `0`, detenete: no instales como root. Si el primero falla, no estás en
el checkout de `pegasus-harness`; pedile a la persona la ruta correcta antes de seguir.

## 2. Descargar los cinco assets del release y verificarlos

Sustituí `RELEASE_TAG` por el tag que la persona pidió. Cada asset tiene que venir de la misma
publicación de GitHub Releases — no combines wheel, `requirements.txt` o el shim de tags distintos.

```sh
RELEASE_TAG="v4.0.0"
DOWNLOAD_DIR="$HOME/Downloads/pegasus-$RELEASE_TAG"
mkdir -p "$DOWNLOAD_DIR"
cd "$DOWNLOAD_DIR"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"
WHEEL="pegasus_harness-4.0.0-py3-none-any.whl"

curl -fL -O "$BASE_URL/$WHEEL"
curl -fL -O "$BASE_URL/$WHEEL.sha256"
curl -fL -O "$BASE_URL/requirements.txt"
curl -fL -O "$BASE_URL/requirements.txt.sha256"
curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c "$WHEEL.sha256" requirements.txt.sha256 pegasus.sha256
python3 -c "
import json, sys
manifest = json.load(open('release-manifest.json'))
assert manifest['schema'] == 'pegasus-harness-release/v4', manifest['schema']
assert manifest['tag'] == '$RELEASE_TAG', manifest['tag']
names = {a['name'] for a in manifest['assets']}
assert names == {'$WHEEL', 'requirements.txt', 'pegasus'}, names
print('release-manifest.json: coincide con', manifest['tag'], manifest['commit'])
"
```

**Detenete y no sigas si:** `sha256sum -c` reporta `FAILED` para cualquiera de los tres, o el script de
Python levanta `AssertionError`. Ninguno de los dos casos es recuperable descargando de nuevo del mismo
tag: si el tag ya publicó bytes que no calzan con su propio manifest, avisale a la persona y esperá
instrucciones — no lo instales.

*No ejecutado en esta verificación: `curl` contra GitHub necesita red, prohibida en este entorno de
trabajo. Lo que sí se probó, contra un wheel construido localmente y su propio
`release-manifest.json` generado por `tools/build_release_evidence.py`, es que `sha256sum -c` y la
comparación de `schema`/`tag`/`assets` distinguen exactamente un archivo correcto de uno alterado
— ver el reporte de esta tarea para la corrida real y el caso negativo.*

## 3. Instalar el venv privado

```sh
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pegasus-harness"
python3 -m venv "$DATA_DIR/venv"
echo "venv: $?"

"$DATA_DIR/venv/bin/python" -m pip install --require-hashes -r requirements.txt
echo "requirements: $?"

"$DATA_DIR/venv/bin/python" -m pip install --no-deps "$WHEEL"
echo "wheel: $?"
```

Reportá los tres códigos de salida. El primero necesita red (baja `PyYAML` y lo verifica contra el
hash ya fijado en `requirements.txt`); si no hay red, detenete acá y decíselo a la persona en vez de
improvisar una instalación parcial. El segundo no necesita red: instala el wheel que ya verificaste, y
`--no-deps` evita que vuelva a resolver algo que el paso anterior ya fijó.

*Ejecutados los tres comandos tal cual en esta verificación. `python3 -m venv` y el `pip install
--no-deps` contra el wheel terminaron en `0`, éste último con `Successfully installed
pegasus-harness-4.0.0` (publicado). El `pip install --require-hashes -r requirements.txt` no se pudo completar sin red — se
intentó forzarlo íntegramente offline y no hay wheel de `PyYAML` fijado por hash disponible en este
disco; queda documentado como el paso que un agente real debe reportar sin poder saltear.*

## 4. Dejar el lanzador en el PATH

```sh
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
install -m 755 pegasus "$BIN_DIR/pegasus"

case ":$PATH:" in
  *":$BIN_DIR:"*) echo "PATH: ya incluye $BIN_DIR" ;;
  *) echo "PATH: falta $BIN_DIR -- agregalo antes de invocar 'pegasus' en una shell nueva" ;;
esac
```

Si falta en el PATH, no lo agregues vos mismo al perfil de shell de la persona sin que lo pida: decíselo
y esperá.

*Ejecutado tal cual: `install -m 755` dejó el shim con permiso `0755`, y el `case` se probó con las dos
ramas (ausente y presente) sobre un `PATH` de prueba.*

## 5. Verificar y reportar

```sh
pegasus doctor
```

Si el paso 3 no pudo completar `pip install --require-hashes` por falta de red, este comando falla al
importar `yaml` — reportá exactamente ese traceback, no lo escondas ni lo reintentes en un loop.
Con las dependencias instaladas, reporta qué CLIs anfitrionas detecta esta cuenta.

**No uses `pegasus setup` para arreglar una instalación a medias.** Sirve desde un checkout, no
desde una instalación hecha con esta guía: reconstruir el venv exige el wheel y el lockfile con los
hashes, y una instalación no guarda ninguno de los dos. El comando lo dice y no toca nada, así que
si lo corrés vas a leer una línea que empieza con `setup builds the private venv out of this
project's own checkout`. Si el venv quedó a medias, repetí los pasos 3 y 4 — son idempotentes.

*Se probaron las dos situaciones: sin completar el paso 3 por falta de red, `pegasus doctor` falló al
importar `yaml` con el traceback esperado; con `PyYAML` disponible por otra vía sólo para esta
verificación, `pegasus doctor` corrió de punta a punta a través del shim y reportó
`OpenCode: not found on this machine.` (correcto para esa cuenta de prueba). `pegasus setup` invocado
sobre esa misma instalación de prueba se negó nombrando el lockfile que falta, sin escribir nada.*

## Instalar en OpenCode y elegir MCPs

Con el venv instalado y `pegasus` en el PATH, identificá primero el binario de OpenCode en la shell
real de la cuenta -- no asumas que una shell de login comparte el mismo PATH que la sesión del agente:

```sh
command -v opencode
```

Pedile a la persona una decisión explícita por cada MCP que quiera instalar; hoy el único servidor
remoto embarcado en el contenido es `context7`. Traducí cada decisión a `--mcp <id>` (instalar) o a la
ausencia del flag (no instalar) -- no hay `--confirm`/`--decline` en v4, un servidor no nombrado
simplemente no se instala:

```sh
pegasus install --cli opencode --dry-run --mcp context7
```

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
