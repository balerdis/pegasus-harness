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

## 2. Descargar los assets del release y verificarlos

Sustituí `RELEASE_TAG` por el tag que la persona pidió. Cada asset tiene que venir de la misma
publicación de GitHub Releases — no combines el wheel y el shim de tags distintos.

```sh
RELEASE_TAG="v4.1.2"
DOWNLOAD_DIR="$HOME/Downloads/pegasus-$RELEASE_TAG"
mkdir -p "$DOWNLOAD_DIR"
cd "$DOWNLOAD_DIR"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"
WHEEL="pegasus_harness-4.1.2-py3-none-any.whl"

curl -fL -O "$BASE_URL/$WHEEL"
curl -fL -O "$BASE_URL/$WHEEL.sha256"
curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c "$WHEEL.sha256" pegasus.sha256
python3 -c "
import json, sys
manifest = json.load(open('release-manifest.json'))
assert manifest['schema'] == 'pegasus-harness-release/v4', manifest['schema']
assert manifest['tag'] == '$RELEASE_TAG', manifest['tag']
names = {a['name'] for a in manifest['assets']}
assert names == {'$WHEEL', 'pegasus'}, names
print('release-manifest.json: coincide con', manifest['tag'], manifest['commit'])
"
```

**Detenete y no sigas si:** `sha256sum -c` reporta `FAILED` para cualquiera de los dos, o el script de
Python levanta `AssertionError`. Ninguno de los dos casos es recuperable descargando de nuevo del mismo
tag: si el tag ya publicó bytes que no calzan con su propio manifest, avisale a la persona y esperá
instrucciones — no lo instales.

Esta es la única sección de toda la instalación que necesita red: descargar los bytes que se van a
instalar. Pegasus no tiene dependencias de terceros, así que ningún paso posterior vuelve a salir a
internet.

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

"$DATA_DIR/venv/bin/python" -m pip install --no-deps "$WHEEL"
echo "wheel: $?"
```

Reportá los dos códigos de salida. Ninguno de los dos necesita red: Pegasus no tiene dependencias de
terceros, así que el único `pip install` que queda instala el wheel que ya verificaste, y `--no-deps`
evita que vuelva a resolver algo.

*Ejecutados los dos comandos tal cual, sin red, contra un wheel construido localmente: `python3 -m
venv` y el `pip install --no-deps` terminaron en `0`, éste último con `Successfully installed
pegasus-harness-4.1.2`. Se confirmó además que el venv resultante no tiene `PyYAML` instalado
(`import yaml` falla ahí) y que `pegasus doctor` corre igual — ver el paso 5.*

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

Como el paso 3 no depende de red, si terminó con código `0` este comando ya puede correr. Reporta qué
CLIs anfitrionas detecta esta cuenta.

**No uses `pegasus setup` para arreglar una instalación a medias.** Sirve desde un checkout, no
desde una instalación hecha con esta guía: reconstruir el venv exige el propio checkout (su
`pyproject.toml` y su `bin/pegasus`), y una instalación no guarda ninguno de los dos. El comando lo
dice y no toca nada, así que si lo corrés vas a leer una línea que empieza con `setup builds the
private venv out of this project's own checkout`. Si el venv quedó a medias, repetí los pasos 3 y 4
— son idempotentes.

*Se probó de punta a punta contra el wheel construido localmente e instalado sin red: `pegasus
doctor`, invocado a través del shim, corrió completo sin `PyYAML` instalado en el venv y reportó
`OpenCode: not found on this machine.` (correcto para esa cuenta de prueba). `pegasus setup`,
invocado sobre esa misma instalación, se negó nombrando el checkout que falta, sin escribir nada.*

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
