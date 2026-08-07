# Instalar Pegasus con un agente

Este instructivo es para un agente que asiste a una persona en la cuenta Linux actual. El agente inspecciona y propone; la persona decide los MCPs y mantiene el control de credenciales y modelos.

## Smoke manual RC y distribución final

Para un smoke manual pre-release, usá sólo un conjunto inmutable y coincidente con un tag `v3.1.1-rc.N` publicado (por ejemplo, `v3.1.1-rc.2`). `N` debe ser un entero positivo; no uses otra versión, un tag malformado ni combines números RC.

```text
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1-rc.2/pegasus-harness-v3.1.1-rc.2.tar.gz
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1-rc.2/pegasus-harness-v3.1.1-rc.2.tar.gz.sha256
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1-rc.2/release-manifest.json
```

El preflight acepta cualquier RC `v3.1.1-rc.N` únicamente cuando tag, basename canónico del archive, checksum, manifest, raíz del archive y evidencia interna coinciden. Es una ruta de smoke manual: nunca la presentes como `latest`, no combines assets RC/finales y no la uses como distribución final general.

Para instalar la distribución final, usá exclusivamente los tres assets de `v3.1.1`. Los locators inmutables son:

```text
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1/pegasus-harness-v3.1.1.tar.gz
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1/pegasus-harness-v3.1.1.tar.gz.sha256
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1/release-manifest.json
```

Después de que el release final no-prerelease esté publicado, los mismos basenames deben resolver por `https://github.com/balerdis/pegasus-harness/releases/latest/download/<asset>`. Descargá ambos conjuntos sólo para la verificación operatoria posterior: cada par debe tener el mismo basename, bytes, checksum y `tag: v3.1.1`. No trates un RC ni un redirect sin esa comparación como `latest` válido.

Antes de mostrar comandos de instalación o apply, ejecutá únicamente el preflight read-only sobre los tres assets seleccionados. Descubrí primero el binario de OpenCode en la shell real de la cuenta; no supongas que una shell de login tenga el mismo `PATH`. Si la cuenta lo configura mediante un profile conocido, la persona puede abrir/sourciar ese profile en su propia shell y luego capturar el resultado de `command -v opencode`.

```sh
# Elegí el tag del conjunto de assets que descargaste: RC para smoke o final para distribución.
RELEASE_TAG="v3.1.1-rc.2"
ARCHIVE="pegasus-harness-${RELEASE_TAG}.tar.gz"
CHECKSUM="${ARCHIVE}.sha256"
RELEASE_MANIFEST="release-manifest.json"

test -f "$ARCHIVE" -a -f "$CHECKSUM" -a -f "$RELEASE_MANIFEST"

OPENCODE_BIN="$(command -v opencode || true)"
[ -n "$OPENCODE_BIN" ] || OPENCODE_BIN="$HOME/.opencode/bin/opencode"
[ -x "$OPENCODE_BIN" ] || OPENCODE_BIN="$HOME/.local/bin/opencode"
test -x "$OPENCODE_BIN"

python3 tools/agent_install_preflight.py \
  --archive "$ARCHIVE" \
  --checksum "$CHECKSUM" \
  --release-manifest "$RELEASE_MANIFEST" \
  --opencode "$OPENCODE_BIN" \
  --mcp cbm --mcp engram --mcp playwright --mcp context7 \
  --browser /absolute/path/to/browser
```

Su salida es un único JSON allowlisted; no lee ni muestra configuraciones de OpenCode, valores de entorno, rutas de configuración, credenciales o tokens.

Detenete si el JSON no devuelve `"status": "ready"`. El preflight comprueba una cuenta no-root, Python/OpenCode, identidad del archive/checksum/manifest, snapshot contenido y sólo probes fijos de ejecutables elegidos. Context7 queda como confirmación remota: no se inspecciona configuración para decidirlo. El navegador sólo se exige si se solicita Playwright.

## Inspeccionar el checkout antes de cambiar algo

1. Confirmá que estás en el checkout que la persona eligió y que la terminal no corre como root.
2. Ejecutá `python3 tools/validate_snapshot.py`. Si falla, detenete: no corras el instalador.
3. Revisá el payload real antes de proponer cambios:
   - prompts: `source/opencode/prompts/`;
   - agentes: `source/opencode/agents/`;
   - skills: `source/core/skills/`;
   - comandos: `source/opencode/commands/`;
   - registro de artifacts y destinos: `manifests/artifact-catalog.json`;
   - dependencias locales opcionales y sus contratos: `manifests/release-contract.json`.

El catálogo registra los artifacts de OpenCode y sus destinos; el contrato fija CBM, Engram y Playwright. Context7 es una integración remota opcional que el motor configura solo con confirmación explícita.

## Preparar decisiones, plan y apply

Antes de aplicar, el agente tiene que identificar cada MCP faltante: `cbm`, `engram`, `playwright` y `context7`. Debe pedir confirmación explícita a la persona para **cada** uno y traducir exactamente esa respuesta a una sola opción:

- `--confirm <mcp>` instala o configura ese MCP;
- `--decline <mcp>` no lo descarga, configura ni registra.

El agente no decide, confirma ni rechaza MCPs por su cuenta. Debe registrar literalmente `confirmado` o `rechazado` para **cbm**, **engram**, **playwright** y **context7** antes de distribuir comandos; una decisión ausente bloquea el paso siguiente. Tampoco debe manejar credenciales con `/connect` ni seleccionar modelos con `/models`: esas acciones se difieren a la persona dentro de OpenCode después del apply.

Cuando estén las cuatro decisiones, ejecutá desde el checkout:

```sh
./install.sh --client opencode \
  --confirm context7 \
  --decline cbm --decline engram --decline playwright
```

Adaptá solamente las decisiones que la persona haya dado. El wrapper valida el snapshot, muestra el plan y solo después hace el apply.

## Respetar el estado existente

No fuerces colisiones: Pegasus las informa y preserva los archivos o claves existentes. Después del apply, revisá `opencode debug info` y el journal en `~/.local/share/pegasus-harness/journal-v3.json`. La persona puede usar las herramientas de OpenCode que elija para su propia configuración, pero el agente no debe pedir, leer ni reproducir su contenido.

Si hace falta rollback, usá únicamente el mecanismo de uninstall de Pegasus. El journal permite eliminar solo los artifacts sin cambios que Pegasus creó; no borres configuración ajena ni dependencias no registradas.

La instalación manual canónica está en [INSTALL.md](INSTALL.md); [README.md](README.md) presenta ambas rutas y [MANUAL.md](MANUAL.md) explica el control de modelo y proveedor de la persona.
