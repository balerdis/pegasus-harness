# Pegasus Harness

Pegasus Harness es un conjunto open source con licencia MIT de prompts, agentes, skills, comandos e integraciones opcionales para trabajar con OpenCode de forma más ordenada. Sirve para distintos clientes y repositorios: el flujo queda en manos del equipo que lo usa, no de una configuración particular de cliente.

Pegasus es aditivo. Revisa lo que ya existe, muestra un plan y crea solamente los artifacts seleccionados que faltan. No toma propiedad de una instalación existente de OpenCode, su configuración ni sus archivos.

## Instalación

Pegasus soporta hoy Linux, con OpenCode como único cliente. Un solo comando detecta qué te falta
(Node, OpenCode, el binario `pegasus`), te muestra el plan antes de tocar nada, pide confirmación e
instala sólo eso — no hace falta elegir una versión ni copiar un tag a mano:

```sh
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash
```

Termina dejándote siempre en la interfaz de Pegasus: si instaló algo nuevo, todavía hay que elegir
MCPs y confirmar dentro de OpenCode; si tu entorno ya estaba completo, se abre igual para avisarte si
hay una versión más nueva de pegasus publicada. [INSTALL.md](INSTALL.md) explica paso a paso qué hace ese script, sus flags (`--verify`,
`--yes`, `--no-run`, `--bin-dir`, ...), la interfaz interactiva de Pegasus y el uso por línea de
comandos — incluida la instalación manual, sin el script, para quien prefiera revisar cada paso.

Para confirmar en cualquier momento cómo quedó, y qué está integrado en OpenCode:

```sh
pegasus doctor
```

`pegasus` es un solo archivo: no busca un venv, no depende de nada instalado antes que él, no hace
falta `sudo`. Es Python 3.12+, sin ninguna dependencia de terceros.

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

Para `pegasus install --cli opencode` (y para `update`/`uninstall` con ese mismo `--cli`) necesitás
OpenCode ya instalado en la cuenta: `pegasus` en sí nunca instala OpenCode, sólo se integra con una
instalación existente. Si instalaste con `install.sh` de la sección anterior, esto ya está resuelto —
ese script instala Node y OpenCode antes de llegar a `pegasus`. Si vas a confirmar CBM, verificá que
`codebase-memory-mcp --version` y `codebase-memory-mcp --help` respondan desde el ejecutable local.
Playwright necesita un navegador compatible instalado por separado antes del apply; Pegasus no
descarga navegadores.

Pegasus no configura credenciales, proveedor ni modelo: usá `/connect` para las credenciales del proveedor y `/models` para elegir el modelo.

La ruta asistida por agente empieza en [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md): verifica los assets finales sin leer la configuración de OpenCode y solicita una decisión independiente para cada MCP.

## Más allá de instalar

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para el diseño hexagonal, los puertos y las
decisiones detrás de esta versión, consultá [docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md).

## Licencia

Pegasus Harness se distribuye bajo la [licencia MIT](LICENSE).
