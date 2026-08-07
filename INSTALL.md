# Instalación limpia en una cuenta Linux separada

Este es el recorrido seguro para una persona nueva: OpenCode y la elección de proveedor/modelo son de su cuenta; Pegasus solo agrega sus artifacts. No ejecutes el instalador de OpenCode como root ni copies la configuración de otra persona.

## Camino exacto

### 1. Abrir una shell de la cuenta destino

Desde una cuenta administradora, reemplazá el nombre y entrá a la cuenta Linux nueva. No continúes si `HOME` no es el home esperado.

```sh
export PEGASUS_TARGET_USER="NUEVO_USUARIO"
id "$PEGASUS_TARGET_USER"
sudo -iu "$PEGASUS_TARGET_USER"
printf 'usuario=%s home=%s\n' "$(id -un)" "$HOME"
```

### 2. Instalar y localizar OpenCode como esa persona

El instalador oficial corre dentro de esta shell, por lo que instala para la cuenta destino. No uses `sudo` en este paso.

```sh
curl -fsSL https://opencode.ai/install | bash

OPENCODE_BIN="$(command -v opencode || true)"
if [ -z "$OPENCODE_BIN" ] && [ -x "$HOME/.opencode/bin/opencode" ]; then
  OPENCODE_BIN="$HOME/.opencode/bin/opencode"
fi
if [ -z "$OPENCODE_BIN" ] && [ -x "$HOME/.local/bin/opencode" ]; then
  OPENCODE_BIN="$HOME/.local/bin/opencode"
fi
test -n "$OPENCODE_BIN" || { printf '%s\n' 'OpenCode no quedó en PATH, ~/.opencode/bin ni ~/.local/bin.' >&2; exit 1; }
"$OPENCODE_BIN" --version
printf 'OpenCode: %s\n' "$OPENCODE_BIN"
```

La ruta real puede ser `~/.opencode/bin/opencode` o `~/.local/bin/opencode`; el valor de `OPENCODE_BIN` evita asumir una de las dos.

### 3. Descargar y comprobar el RC publicado que incluye este cambio

El release final no adjunta los tres assets de distribución. Usá únicamente el RC publicado cuyas notas declaren este fallback de modelo; un RC anterior no lo incorpora solo por tener el mismo nombre de producto. Reemplazá `v3.1.0-rc.N` por ese tag antes de ejecutar los comandos.

```sh
RELEASE_TAG="v3.1.0-rc.N"
mkdir -p "$HOME/Downloads/pegasus-$RELEASE_TAG"
cd "$HOME/Downloads/pegasus-$RELEASE_TAG"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"
ARCHIVE="pegasus-harness-$RELEASE_TAG.tar.gz"
curl -fL -O "$BASE_URL/$ARCHIVE"
curl -fL -O "$BASE_URL/$ARCHIVE.sha256"
sha256sum -c "$ARCHIVE.sha256"
tar -xzf "$ARCHIVE"
cd "pegasus-harness-$RELEASE_TAG"
python3 tools/validate_snapshot.py
```

Seguís únicamente si el checksum termina en `OK` y el validador termina en `PASS`.

### 4. Aplicar Pegasus con MCPs selectivos

El comando usa `sudo` solamente para que el wrapper entre de manera explícita a la misma cuenta destino. Arrancá sin MCPs: elegí uno por vez más adelante.

```sh
sudo ./install.sh --target-user "$(id -un)" --client opencode \
  --decline cbm --decline engram --decline playwright --decline context7
```

Para sumar uno, confirmá solo ese MCP y rechazá los demás. Por ejemplo, Context7:

```sh
sudo ./install.sh --target-user "$(id -un)" --client opencode \
  --confirm context7 \
  --decline cbm --decline engram --decline playwright
```

Revisá el plan antes de aplicar: el target debe ser esta cuenta nueva. Pegasus no instala navegadores; confirmá Playwright únicamente después de preparar un navegador compatible por fuera de Pegasus.

### 5. Verificar, conectar y elegir el modelo

```sh
"$OPENCODE_BIN" debug config
"$OPENCODE_BIN" debug info
test -f "$HOME/.local/share/pegasus-harness/journal-v3.json" && printf '%s\n' 'journal de Pegasus presente'

mkdir -p "$HOME/practica/ejemplo"
cd "$HOME/practica/ejemplo"
"$OPENCODE_BIN"
```

Dentro de OpenCode, ejecutá `/connect` para configurar las credenciales del proveedor de esta cuenta. Después ejecutá `/models` para elegir el modelo. Hacé ambas cosas antes de pedir trabajo a Pegasus. Pegasus no contiene credenciales ni un `model` por agente: el modelo elegido queda bajo control de esta cuenta. Si querés un default persistente, configurá el `model` global en tu propio `~/.config/opencode/opencode.json`; no hace falta editar los agentes de Pegasus.

## Control final

- [ ] OpenCode fue instalado y ejecutado como la cuenta destino, no root.
- [ ] Se verificaron el archive, checksum y snapshot extraído antes del apply.
- [ ] Se confirmó como máximo el MCP que se decidió usar.
- [ ] `opencode debug config` reconoce el payload y el journal existe.
- [ ] `/connect` configuró las credenciales del proveedor antes del primer uso de Pegasus.
- [ ] `/models` seleccionó el modelo antes del primer uso de Pegasus.
- [ ] Proveedor, credenciales y modelo siguen bajo control de la cuenta destino.

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para la política de ownership y rollback, consultá [docs/instalacion-aditiva-v3.md](docs/instalacion-aditiva-v3.md).
