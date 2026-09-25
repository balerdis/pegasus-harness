# Pegasus Harness

Pegasus Harness es un conjunto open source con licencia MIT de prompts, agentes, skills, comandos e integraciones opcionales para trabajar con un CLI de agentes de forma más ordenada. Hoy soporta dos: OpenCode y Claude Code. Sirve para distintos clientes y repositorios: el flujo queda en manos del equipo que lo usa, no de una configuración particular de cliente.

Pegasus es aditivo. Revisa lo que ya existe, muestra un plan y crea solamente los artifacts seleccionados que faltan. No toma propiedad de una instalación existente del CLI elegido, su configuración ni sus archivos.

## Instalación

Pegasus soporta hoy Linux, con OpenCode y Claude Code como clientes. El mismo comando de siempre
detecta qué te falta (Node, el CLI, el binario `pegasus`), te muestra el plan antes de tocar nada,
pide confirmación e instala sólo eso — no hace falta elegir una versión ni copiar un tag a mano:

```sh
curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash
```

El comando nunca elige un CLI por su cuenta: si la cuenta ya tiene exactamente uno de los dos
instalado, ese es el destino y el mismo prompt de confirmación lo cubre; si no hay ninguno instalado,
o hay más de uno, y hay una terminal, te pregunta cuál; sin terminal (por ejemplo, corriendo sin tty),
falla nombrando `--cli` en vez de adivinar. `./install.sh --cli claudecode` o `--cli opencode` elige
sin preguntar.

Termina dejándote siempre en la interfaz de Pegasus: si instaló algo nuevo, bajo OpenCode todavía hay
que elegir MCPs y confirmar dentro de esa interfaz — bajo Claude Code no hace falta reiniciar nada,
la configuración se lee tal como quedó escrita; si tu entorno ya estaba completo, se abre igual para
avisarte si hay una versión más nueva de pegasus publicada. [INSTALL.md](INSTALL.md) explica paso a
paso qué hace ese script, sus flags (`--cli`, `--verify`, `--yes`, `--no-run`, `--bin-dir`, ...), la
interfaz interactiva de Pegasus y el uso por línea de comandos — incluida la instalación manual, sin
el script, para quien prefiera revisar cada paso.

Para confirmar en cualquier momento cómo quedó, y qué está integrado en cada CLI que esta cuenta tiene:

```sh
pegasus doctor
```

`pegasus` es un solo archivo: no busca un venv, no depende de nada instalado antes que él, no hace
falta `sudo`. Es Python 3.12+, sin ninguna dependencia de terceros.

### Con un agente

Usá [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) si un agente va a inspeccionar el checkout, preparar el plan y pedirte cada decisión pendiente.

## Qué incluye

Pegasus distribuye un payload seleccionado para el CLI elegido, no un home directory de reemplazo:

- comandos para SDD, contexto, handoff, creación y registro de skills;
- el orquestador de Pegasus y sus roles de implementación/verificación;
- skills reutilizables y sus referencias;
- plugins locales seleccionados e integraciones opcionales cuando se confirman: CBM, Engram, Playwright, Context7 y Jira. Son cinco y se eligen de a uno — un servidor que no pedís no se instala, y no deja configuración ni dependencia huérfana.

Jira es el que conviene leer antes de elegirlo: llega al servidor remoto propio de Atlassian, necesita
una autorización única por fuera de Pegasus (bajo OpenCode, `opencode mcp auth jira`) antes de que
cualquier herramienta conteste, y no retiene ninguna — lo que esa cuenta permita en Atlassian, un
agente que reciba el servidor lo puede hacer, incluido crear, transicionar y editar tickets.
[MANUAL.md](MANUAL.md) lo detalla junto con los otros cuatro, para OpenCode.

## Qué soporta cada CLI

Cada adapter declara, en su propio manifest, exactamente lo que implementa — nunca lo que el CLI
podría hacer en teoría. Esta tabla se deriva de ese manifest, no se retipea a mano:
`test_adapter_documentation_coverage.py` la compara, celda por celda, contra
`pegasus.adapters.available()`, así que un tercer CLI que se registre sin agregar su fila hace fallar
ese test en vez de quedar indocumentado en silencio, como le pasó a Claude Code antes de este cambio.

| CLI | skills | system_prompt | slash_commands | sub_agents | prompts | mcp | per_agent_model | tier |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenCode | sí | sí | sí | sí | sí | sí | sí | full |
| Claude Code | sí | sí | sí | sí | no | sí | no | partial |

Dos columnas merecen una aclaración, porque son diferencias que se notan al usar el producto, no
detalles internos:

- **`prompts`**: bajo OpenCode, el prompt de un agente vive en un archivo propio, separado del
  archivo del agente (`{file:...}` los conecta). Bajo Claude Code no hay ese segundo archivo: el
  prompt es el cuerpo del propio archivo del agente, un solo artifact en vez de dos.
- **`per_agent_model`**: bajo OpenCode, `pegasus models set` asigna un modelo distinto por agente,
  leyendo el catálogo real de modelos y credenciales de esa instalación, y ese modelo queda escrito en
  la configuración del agente. Claude Code no tiene un catálogo de modelos en disco que leer — resuelve
  modelo y proveedor en el momento, no desde un archivo—, así que su adapter no declara esta capacidad.
  Los tres subcomandos de `models` (`set`, `unset`, `list`) lo comprueban antes que cualquier otra cosa
  y se niegan a correr contra `--cli claudecode`, nombrando el CLI y explicando por qué: no hay
  catálogo de modelos que leer, y por lo tanto nada que este comando pueda escribir o reportar.

Y una que corre al revés de lo que uno esperaría: instalar o actualizar bajo Claude Code no pide
reiniciar nada — lee la configuración tal como quedó escrita, sin ningún paso de activación. Bajo
OpenCode sí hace falta reiniciar, porque esa CLI lee la configuración de sus agentes una sola vez, al
arrancar.

Los dos guardan su configuración en raíces distintas: OpenCode en `~/.config/opencode` (respeta
`XDG_CONFIG_HOME`), Claude Code en `~/.claude` (respeta `CLAUDE_CONFIG_DIR`, no `XDG_CONFIG_HOME`).

## Cómo encaja el flujo

La versión corta es: primero entender el pedido y después elegir la ruta. Una consulta se responde sin tocar nada, un cambio trivial y ya entendido se hace directo, y la mayoría de los cambios comunes van por FTD, con un record en `docs/ftd/` y sin tener que pedirlo. SDD se propone sólo cuando hay que fijar antes del código un contrato o una decisión que va a revisar alguien que no está en la implementación, o una spec contra la que otros van a construir; el tamaño del cambio no decide ninguna ruta. [docs/metodologia.md](docs/metodologia.md) explica las rutas y las responsabilidades de SDD, FTD, TDD, OpenSpec, Engram y ChainPR sin esconder los límites operativos.

En SDD, `sdd-verify` es la única autoridad para declarar listo para archivar un cambio. Fuera de SDD, el listo lo declara quien pidió el trabajo, a partir de la evidencia observada, y si lo escribió él mismo lo dice. CBM ayuda a descubrir estructura y callers; no reemplaza una prueba de comportamiento que pasó.

## Prerrequisitos por CLI

Para `pegasus install --cli <id>` (y para `update`/`uninstall` con ese mismo `--cli`) necesitás ese
CLI ya instalado en la cuenta: `pegasus` en sí nunca instala OpenCode ni Claude Code, sólo se integra
con una instalación existente. Si instalaste con `install.sh` de la sección anterior, esto ya está
resuelto — ese script instala Node y el CLI elegido antes de llegar a `pegasus`, para cualquiera de
los dos (Node es incondicional: parte de los MCPs que Pegasus distribuye se materializa con npm,
sea cual sea el CLI de destino).

Si vas a confirmar CBM, verificá que `codebase-memory-mcp --version` y `codebase-memory-mcp --help`
respondan desde el ejecutable local. Playwright necesita un navegador compatible instalado por
separado antes del apply; Pegasus no descarga navegadores. Context7 y Jira son remotos: no descargan
nada, pero necesitan salida a la red, y Jira además su autorización única (bajo OpenCode, `opencode
mcp auth jira`), que Pegasus no puede hacer por vos.

Pegasus no configura credenciales, proveedor ni modelo. Bajo OpenCode, usá `/connect` para las
credenciales del proveedor y `/models` para elegir el modelo; bajo Claude Code, esa configuración es
la de tu propia cuenta y queda fuera de lo que Pegasus toca en cualquiera de los dos casos.

La ruta asistida por agente empieza en [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md): verifica los
assets finales sin leer la configuración del CLI elegido y solicita una decisión independiente para
cada MCP.

## Más allá de instalar

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para el diseño hexagonal, los puertos y las
decisiones detrás de esta versión, consultá [docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md).

Lo que el producto hace así a propósito y no va a cambiar —entre otras cosas, que una edición tuya
sobre un archivo instalado no sobreviva al próximo `install`— está en
[Limitaciones aceptadas](docs/arquitectura/arquitectura.md#limitaciones-aceptadas), cada una con su
motivo y con qué podés hacer al respecto. Lo que todavía está por decidirse o por hacerse, en
[Deudas sin unidad asignada](docs/arquitectura/arquitectura.md#deudas-sin-unidad-asignada).

## Licencia

Pegasus Harness se distribuye bajo la [licencia MIT](LICENSE).
