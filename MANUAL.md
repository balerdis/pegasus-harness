# Manual de uso: Pegasus Harness + OpenCode

Este manual describe cómo usar Pegasus 4 una vez instalado: qué decide, qué preserva de tu cuenta y cómo se trabaja el día a día con OpenCode. Para instalarlo no hay procedimiento acá — está en [INSTALL.md](INSTALL.md) (manual) y en [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) (asistido por un agente).

## Qué es Pegasus en esta versión

Pegasus 4 no trae un instalador propio ni un tarball: es un paquete de Python que vive en un venv privado (`$XDG_DATA_HOME/pegasus-harness/venv`, o `~/.local/share/pegasus-harness/venv` si esa variable no está definida), con un lanzador `pegasus` en tu PATH. `pegasus` sin argumentos abre una TUI cuando corre en una terminal; sin terminal, o con un subcomando explícito, se comporta como CLI. Ambas superficies llaman al mismo motor: nada que la TUI pueda hacer le está vedado a los flags.

Antes de usarlo necesitás OpenCode instalado por fuera de Pegasus — Pegasus no lo instala, actualiza ni desinstala — y una cuenta Linux no-root, porque escribe únicamente en tu propio `~/.config` y `~/.local`.

## Instalar el payload en OpenCode

Con el venv ya armado y `pegasus` en el PATH, el comando que aplica el payload es:

```sh
pegasus install --cli opencode --dry-run --mcp <id>
```

`--dry-run` muestra el plan sin escribir nada; repetir el mismo comando sin ese flag lo aplica. Un servidor MCP no nombrado con `--mcp` no se instala — no hay `--confirm`/`--decline` como en v3, la ausencia del flag ya es la decisión de no instalarlo. Podés repetir `--mcp` para pedir varios.

Si el plan encuentra una clave o un archivo tuyo en el destino, lo informa y lo preserva: no lo adopta como si fuera de Pegasus. El payload de OpenCode queda bajo `~/.config/opencode/` (o el `XDG_CONFIG_HOME` que tengas seteado): las skills en `skills/`, los comandos en `commands/`, el system prompt de Pegasus como `pegasus-AGENTS.md` (el nombre lleva el prefijo del binario instalado, `pegasus` en esta distribución; otra distribución del mismo motor lo instala con su propio nombre), y los agentes declarados dentro de `opencode.json` — OpenCode no los materializa como archivos aparte. Después de un apply exitoso, cerrá y reiniciá OpenCode para que cargue la configuración nueva.

## Qué hacen los cinco MCPs opcionales

| MCP | Uso práctico | Decisión |
| --- | --- | --- |
| CBM (`codebase-memory-mcp`) | Buscar estructura, callers, flujos e impacto de código. | Es inteligencia de código; no prueba comportamiento. |
| Engram | Recuperar decisiones, progreso y resúmenes entre sesiones, con el protocolo de memoria persistente. | La memoria no puede sobreescribir la evidencia actual. |
| Playwright | Probar una frontera de navegador cuando el proyecto lo necesita. | Requiere un navegador compatible instalado por separado; Pegasus no lo descarga. |
| Context7 | Consultar documentación del proveedor de forma remota. | Es remoto, igual que Jira; confirmá el acceso a esa red por separado. |
| Jira | El tracker de tu organización, a través del servidor remoto propio de Atlassian. Qué herramientas expone lo decide Atlassian, no Pegasus. | Necesita una autorización única, `opencode mcp auth jira`, antes de que cualquier herramienta conteste, y nada más te lo va a avisar. No retiene ninguna herramienta: lo que ese servidor permita, un agente que lo reciba lo puede hacer — crear, transicionar y editar, no sólo leer. |

Instalá solo lo que el equipo vaya a usar: un servidor no pedido con `--mcp` no deja config ni dependencia huérfana.

## Dar acceso a un MCP que vos mismo administrás

Pegasus renderiza cada agente con una base que niega todo (`{"*": false}`) más una lista de los servidores que él mismo instala. Un MCP que instalaste y administrás por tu cuenta (Sentry, Figma, o cualquier otro) queda fuera de esa lista aunque figure en tu `opencode.json`: OpenCode combina el bloque de permisos propio del agente al final, así que si Pegasus no le abre la puerta a esa clave, ningún agente puede usarla, sin importar qué diga tu configuración general.

Si ya administrás tu propia clave `jira` con `mcp grant` (alcanza a los trece agentes) y más adelante un `install`/`update` selecciona el `jira` que Pegasus embarca (que sólo alcanza a los ocho agentes que llevan Context7), la colisión no aborta nada: `grant_mcp` descarta en silencio el grant que venías arrastrando, por considerarlo redundante, y tu alcance baja de trece agentes a ocho sin más aviso que el `grant_warnings` del report.

`pegasus mcp` es la palanca para eso. A diferencia de los MCPs que Pegasus instala, acá no hay elección por agente: la clave se otorga a todos los agentes por igual, porque hacerlo agente por agente volvería tediosa la tarea de sumar un MCP más.

```sh
pegasus mcp grant --cli opencode sentry-mcp
pegasus mcp list --cli opencode
pegasus mcp revoke --cli opencode sentry-mcp
```

`grant` rechaza una clave que tu propia configuración de OpenCode no declara bajo `mcp` — nombra ahí mismo cuáles sí declara, para que un error de tipeo no termine en un permiso que nadie nota que falta. `revoke` sobre una clave que nunca otorgaste no es un error: informa que ya estaba en ese estado y sale en `0`. `list` muestra lo que está otorgado ahora, y de las claves que tu configuración declara y todavía no otorgaste, cuáles `grant` aceptaría tal como está la instalación — nunca una que `grant` fuera a rechazar. Una clave declarada que Pegasus ya alcanza por agente (un servidor propio de esta instalación, o una clave ya ligada) se muestra aparte, marcada como ya cubierta, en vez de desaparecer del listado sin explicación.

Los tres reaplican la configuración renderizada al terminar — igual que `pegasus install` — así que el cambio ya queda escrito en `opencode.json`. Como con cualquier cambio a los agentes, hace falta reiniciar OpenCode para que lo lea: sigue leyendo la configuración de agentes una sola vez, al arrancar. `pegasus update --cli opencode` reaplica las claves otorgadas junto con el resto de la selección, sin flags.

Lo mismo está disponible desde la TUI (`pegasus`, sin argumentos), en el menú principal → `Grant MCP servers` → elegí el CLI. La pantalla lista las claves que `mcp list` reporta como `available` para esa instalación, cada una tildada o no según si ya está otorgada; espacio o enter la tilda o destilda, y `Continue` aplica de una sola vez todo lo otorgado y todo lo revocado — y sólo cuenta como aplicado lo que su propio llamado efectivamente logró, nunca lo pedido sin más si algo se rechazó mientras tanto. Si no hay ningún servidor propio para mostrar, la pantalla explica cuál de dos motivos es: no instalaste ninguno todavía (instalalo en OpenCode como siempre lo harías, y volvé acá a otorgarlo), o ya instalaste uno pero Pegasus ya lo alcanza por agente y nombra cuál — ahí no hay nada para hacer, no es que la detección haya fallado. Si la instalación tiene una ligadura sin resolver (`--mcp id=<clave>` sin la clave nunca registrada), la pantalla lo dice en vez de listar nada: mientras eso siga así, `grant`/`revoke` se niegan para cualquier clave, no sólo la ligada, y hace falta resolverlo primero (ver más arriba). El resultado avisa el mismo reinicio que ya se menciona arriba.

Si más adelante un `install` liga un servidor propio de Pegasus (`--mcp id=<clave>`) bajo la misma cadena que una clave que ya habías otorgado, esa clave otorgada queda redundante y el `install` la descarta en vez de fallar — el servidor sigue siendo alcanzable a través de los agentes que ahora lo declaran. El comando avisa qué clave descartó; si no era lo que querías, volvé a otorgarla con `pegasus mcp grant`.

## Dar acceso a un directorio de trabajo propio

OpenCode pregunta por un permiso separado, `external_directory`, apenas una herramienta de archivo o `bash` apunta a algo fuera del worktree del proyecto. Cada agente que Pegasus instala ya trae la excepción que necesita para leer sus propias skills, pero un directorio que vos necesitás — un worktree enlazado, un árbol de scratch fuera del repo — es un dato que Pegasus no puede conocer de antemano, y no hay forma de agregarlo a mano: Pegasus reclama la entrada completa de cada agente en `opencode.json`, así que una excepción escrita a mano la pisa el próximo `install`/`update`.

```sh
pegasus directory grant --cli opencode /home/vos/worktrees/otro-repo
pegasus directory revoke --cli opencode /home/vos/worktrees/otro-repo
```

`grant` acepta cualquier ruta absoluta que no sea la raíz del filesystem (`/`), no contenga un metacarácter de glob (`*`, `?`, `[`, `]`), y no sea el directorio de configuración de OpenCode, el directorio de datos propio de Pegasus (donde vive su journal), ni un ancestro de cualquiera de los dos. El de configuración guarda tus propios servidores; el de datos guarda el registro que `uninstall` usa para decidir qué borrar, así que darle escritura a un agente ahí equivaldría a dejarlo decidir qué se borra en la próxima desinstalación. Fuera de esas restricciones, una ruta relativa o con `..` también se rechaza; el resto se acepta, incluida una ruta fuera de tu home. La ruta se normaliza antes de guardarse (una barra final o `//` repetidas colapsan a la misma forma), así que `grant`/`revoke` con distinta grafía de la misma ruta se reconocen entre sí. `revoke` sobre una ruta que nunca otorgaste no es un error: informa que ya estaba en ese estado y sale en `0`.

A diferencia de un MCP propio, un directorio otorgado alcanza a **todo** agente, primario o sub-agente por igual — no hay recorte por agente que preservar, así que no hace falta. Los dos reaplican la configuración renderizada al terminar, igual que `pegasus mcp grant`, así que el cambio ya queda escrito en `opencode.json` y sobrevive a cada `install`/`update` posterior sin que haga falta repetirlo. Como con cualquier cambio a los agentes, hace falta reiniciar OpenCode para que lo lea.

Este permiso se renderiza como `"ask"`, no como un otorgamiento silencioso: cada vez que un agente lo necesite, OpenCode va a preguntar. La excepción es una corrida no interactiva con `--auto`, `--yolo`, o el flag del runtime que saltea permisos -- ahí el pedido se publica y se auto-aprueba solo, sub-agentes incluidos, así que bajo esos flags el efecto práctico es el mismo que un `allow`.

## Usarlo todos los días

1. Abrí OpenCode dentro del repositorio en el que vas a trabajar.
2. Para un cambio con alcance real, iniciá el flujo SDD (`sdd-init`, `sdd-new` o `sdd-ff`) y completá el pre-chequeo de sesión que pide el orquestador.
3. Dejá que explore, propuesta, spec, diseño y tareas aclaren el cambio antes de `sdd-apply`.
4. Implementá por unidades de trabajo y cerrá con `sdd-verify` cuando estén completas las tareas; `sdd-verify` es la única autoridad de readiness.

Los comandos distribuidos son `sdd-init`, `sdd-new`, `sdd-ff`, `sdd-continue`, `sdd-apply`, `sdd-status`, `sdd-verify`, `sdd-archive`, `sdd-onboard`, `sdd-explore`, además de `context-load`, `context-save`, `handoff-load`, `handoff-save`, `skill-creator` y `skill-registry`. Podés leer su contenido en `~/.config/opencode/commands/` antes de usarlos.

## Elegir proveedor, modelo y esfuerzo

Pegasus distribuye roles, no credenciales ni modelos: ningún agente trae uno asignado por defecto. En el primer arranque, ejecutá `/connect` dentro de OpenCode para configurar las credenciales del proveedor, y `/models` para elegir el modelo que querés usar de forma general. Esas dos decisiones son tuyas y OpenCode las guarda en su propia configuración; Pegasus no las lee ni las reproduce.

Para asignar un modelo puntual a un agente configurable de la línea SDD, Pegasus tiene su propio comando, separado del `/models` de OpenCode:

```sh
pegasus models set --cli opencode --agent sdd-apply --model anthropic/claude-sonnet-5 --effort high
pegasus models list --cli opencode
pegasus models unset --cli opencode --agent sdd-apply
```

Una asignación se guarda de inmediato, pero no queda escrita en la configuración de OpenCode hasta el próximo `pegasus install --cli opencode`: el comando avisa esto mismo si el agente no la tiene todavía. No pongas tokens ni credenciales en el repo, en prompts, ni en comandos versionados.

## Verificar el estado

```sh
pegasus doctor
```

Reporta qué CLIs anfitrionas detecta y qué drift hay entre lo instalado y lo que el contenido actual generaría. No reemplaza una prueba de comportamiento.

Para chequear además que cada servidor MCP instalado arranca y contesta el handshake de MCP:

```sh
pegasus doctor --start-mcp-servers
```

Tiene sentido correrlo después de instalar servidores MCP, o cuando un cliente reporta que uno no conecta. A diferencia de `doctor` a secas, este flag ejecuta los comandos que la configuración tiene guardados — por eso no es el comportamiento por defecto. Por servidor informa `ok` (contestó el handshake), `timeout` (arrancó pero nunca contestó), `exited` (terminó antes de contestar), `invalid` (contestó algo que no es una respuesta MCP válida) o `not-found` (no se pudo arrancar); un servidor configurado como remoto se reporta como tal y no se arranca.

## Deshacer

- `pegasus restore [generación]` vuelve al estado exacto anterior a un comando (o a una generación puntual del historial de snapshots).
- `pegasus uninstall --cli opencode` retira solo lo que el journal reclama como propio.

El journal vive en `$XDG_DATA_HOME/pegasus-harness/journal-v4.json` (o `~/.local/share/pegasus-harness/journal-v4.json`), en un directorio `0700` con el archivo en `0600`. Lo que decide qué se toca es **el journal y nada más**: un archivo que Pegasus nunca creó no se toca nunca, y uno que el journal reclama se retira aunque vos lo hayas editado después. Nunca uses `restore` ni `uninstall` para borrar configuración que ya era tuya.

Una edición tuya sobre un archivo que Pegasus instaló no sobrevive: `install` y `update` la reescriben con la versión del release, y `uninstall` la borra sin aviso equivalente al `overwritten` que sí te dan los otros dos. Lo que te recupera es `pegasus restore`, con cinco generaciones de historial y no más. El motivo de esa política, los dos huecos del aviso y qué hacer en cada caso están en [docs/arquitectura/arquitectura.md#limitaciones-aceptadas](docs/arquitectura/arquitectura.md#limitaciones-aceptadas).

## Próximo paso

- Para el recorrido completo de instalación: [INSTALL.md](INSTALL.md).
- Para instalación asistida por un agente: [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md).
- Para la arquitectura y las decisiones de diseño de v4: [docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md).
