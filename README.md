# Pegasus Harness v3.1

> **Rama de desarrollo de v4.0.0.** El motor de v3 fue retirado de esta rama; el de v4 todavía no existe. Esta rama no instala nada.
>
> - Versión usable: [`main`](https://github.com/balerdis/pegasus-harness/tree/main) y la [release v3.1.1](https://github.com/balerdis/pegasus-harness/releases/tag/v3.1.1).
> - Arquitectura de v4: [docs/pegasus-v4/arquitectura.md](docs/pegasus-v4/arquitectura.md).
> - El texto de abajo describe v3.1 y se reescribe antes de publicar v4.0.0.

Pegasus Harness es un conjunto open source con licencia MIT de prompts, agentes, skills, comandos e integraciones opcionales para trabajar con OpenCode de forma más ordenada. Sirve para distintos clientes y repositorios: el flujo queda en manos del equipo que lo usa, no de una configuración particular de cliente.

Pegasus es aditivo. Revisa lo que ya existe, muestra un plan y crea solamente los artifacts seleccionados que faltan. No toma propiedad de una instalación existente de OpenCode, su configuración ni sus archivos.

## Instalación

### Con instalador

Seguí [INSTALL.md](INSTALL.md) para instalar Pegasus en la cuenta Linux actual.

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

Para `--client opencode`, necesitás Python 3.12+ y OpenCode instalado previamente en la cuenta Linux actual. Si vas a confirmar CBM, verificá que `codebase-memory-mcp --version` y `codebase-memory-mcp --help` respondan desde el ejecutable local. Playwright necesita un navegador compatible instalado por separado antes del apply; Pegasus no descarga navegadores.

Pegasus no configura credenciales, proveedor ni modelo: usá `/connect` para las credenciales del proveedor y `/models` para elegir el modelo.

La ruta asistida por agente empieza en [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md): verifica los assets finales sin leer la configuración de OpenCode y solicita una decisión independiente para cada MCP.

## Validar un checkout

Los checks de v3 se retiraron junto con su motor. Los de v4 llegan con el motor nuevo.

Para validar la versión usable, cambiá a `main`.

## Licencia

Pegasus Harness se distribuye bajo la [licencia MIT](LICENSE).

## Capturas

Las capturas muestran la validación de instalación sobre `v3.1.1-rc.3` y el resultado en OpenCode.

### Instalación verificada

![Descarga, validación e instalación de OpenCode para Pegasus](docs/images/install-harness-1.png)

### Payload aplicado

![Payload de Pegasus aplicado y OpenCode iniciado](docs/images/install-harness-2.png)

### Pegasus en OpenCode

![Pegasus Orchestrator y sus subagentes disponibles en OpenCode](docs/images/install-harness-3.jpeg)
