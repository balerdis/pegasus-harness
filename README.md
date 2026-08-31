# Pegasus Harness

Pegasus Harness es un conjunto open source con licencia MIT de prompts, agentes, skills, comandos e integraciones opcionales para trabajar con OpenCode de forma más ordenada. Sirve para distintos clientes y repositorios: el flujo queda en manos del equipo que lo usa, no de una configuración particular de cliente.

Pegasus es aditivo. Revisa lo que ya existe, muestra un plan y crea solamente los artifacts seleccionados que faltan. No toma propiedad de una instalación existente de OpenCode, su configuración ni sus archivos.

## Instalación

Pegasus es un solo archivo: `pegasus`. Sin wheel, sin venv, sin `pip install` — se descarga, se
verifica su checksum y se deja ejecutable en el PATH. No hace falta `sudo`.

Elegí el tag que vas a instalar en la [página de releases](https://github.com/balerdis/pegasus-harness/releases) y reemplazalo abajo:

```sh
RELEASE_TAG="<el último tag publicado>"
mkdir -p "$HOME/Downloads/pegasus-$RELEASE_TAG"
cd "$HOME/Downloads/pegasus-$RELEASE_TAG"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"
curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
sha256sum -c pegasus.sha256

BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
install -m 755 pegasus "$BIN_DIR/pegasus"
```

Si `sha256sum -c` falla, no sigas: no tenés lo que el release publicó. Si `$BIN_DIR` no queda en tu
PATH, [INSTALL.md](INSTALL.md) explica el porqué y qué hacer (un `source ~/.bashrc` no alcanza).

```sh
pegasus doctor
```

`pegasus` es el único archivo que hace falta: no busca un venv, no depende de nada instalado antes que
él, y es el mismo archivo en Linux y macOS. Es Python 3.12+, sin ninguna dependencia de terceros.

### Con un agente

Usá [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) si un agente va a inspeccionar el checkout, preparar el plan y pedirte cada decisión pendiente.

## Qué incluye

Pegasus distribuye un payload seleccionado para OpenCode, no un home directory de reemplazo:

- comandos para SDD, contexto, handoff, creación y registro de skills;
- el orquestador de Pegasus y sus roles de implementación/verificación;
- skills reutilizables y sus referencias;
- plugins locales seleccionados e integraciones opcionales CBM, Engram, Playwright y Context7 cuando se confirman.

## Cómo encaja el flujo

La versión corta es: primero entender, después especificar, implementar por unidades chicas y probar el resultado. [docs/metodologia.md](docs/metodologia.md) explica las responsabilidades de SDD, TDD, OpenSpec, Engram y ChainPR sin esconder los límites operativos.

Para cambios ejecutables o de configuración, `sdd-verify` es la autoridad final de readiness. CBM ayuda a descubrir estructura y callers; no reemplaza una prueba de comportamiento que pasó.

## Prerrequisitos de OpenCode

Para `--client opencode`, necesitás OpenCode instalado previamente en la cuenta actual. Si vas a confirmar CBM, verificá que `codebase-memory-mcp --version` y `codebase-memory-mcp --help` respondan desde el ejecutable local. Playwright necesita un navegador compatible instalado por separado antes del apply; Pegasus no descarga navegadores.

Pegasus no configura credenciales, proveedor ni modelo: usá `/connect` para las credenciales del proveedor y `/models` para elegir el modelo.

La ruta asistida por agente empieza en [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md): verifica los assets finales sin leer la configuración de OpenCode y solicita una decisión independiente para cada MCP.

## Más allá de instalar

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para el diseño hexagonal, los puertos y las
decisiones detrás de esta versión, consultá [docs/pegasus-v4/arquitectura.md](docs/pegasus-v4/arquitectura.md).

## Licencia

Pegasus Harness se distribuye bajo la [licencia MIT](LICENSE).
