# Manual de uso: Pegasus Harness + OpenCode

Este manual describe cómo usar Pegasus 6 una vez instalado: qué decide, qué preserva de tu cuenta y cómo se trabaja el día a día con OpenCode. Para instalarlo no hay procedimiento acá — está en [INSTALL.md](INSTALL.md) (manual) y en [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) (asistido por un agente).

## Qué es Pegasus en esta versión

Pegasus 6 es un solo archivo ejecutable: un `zipapp` de Python con shebang y bit ejecutable, que se instala en `~/.local/bin/pegasus` y no depende de nada instalado antes que él — el paquete no declara ninguna dependencia de terceros, así que no hay entorno privado que armar ni que mantener. `pegasus` sin argumentos abre una TUI cuando corre en una terminal; sin terminal, o con un subcomando explícito, se comporta como CLI. Ambas superficies llaman al mismo motor: nada que la TUI pueda hacer le está vedado a los flags. La versión mayor que nombra este párrafo no se retipea acá: la deriva del árbol `ManualNamesTheEntryPointThisReleaseShipsTest` (`tests/test_manual_figures.py`), que además comprueba contra el árbol el destino del binario y que no haya quedado ninguna dependencia que aislar.

Antes de usarlo necesitás OpenCode ya instalado en la cuenta: el binario `pegasus` no lo instala, actualiza ni desinstala — sólo se integra con una instalación existente, y si no la encuentra se niega antes de escribir nada. Quien sí lo instala es `install.sh`, el script que corre el comando de una sola línea con el que empieza [INSTALL.md](INSTALL.md): trae Node y OpenCode antes de llegar al binario, así que si instalaste por ahí eso ya está resuelto, y qué hace exactamente está en [su propia sección](INSTALL.md#1-qué-hace-installsh). También hace falta una cuenta Linux no-root, porque Pegasus escribe únicamente en tu propio `~/.config` y `~/.local`. Las dos mitades se corren en vez de afirmarse: `ManualSaysWhoInstallsOpenCodeTest` (`tests/test_manual_prerequisites.py`) le pide un `install` a una máquina sin OpenCode y le pide su plan al script contra un home descartable, y exige que esta línea nombre todo lo que ese plan trae.

## Usar la interfaz interactiva de Pegasus (la TUI)

Correr `pegasus` sin ningún subcomando, en una terminal, abre un menú — no imprime ayuda ni corre
nada por sí solo. Es el camino pensado para una persona que está preparando su propia máquina y quiere
ver qué va a pasar antes de que pase: cada pantalla de selección va seguida de una vista previa del
plan, y recién al confirmar esa vista previa se escribe algo de verdad. Nada se instala por elegirlo
en el menú; se instala al confirmar la pantalla de resultado de esa elección.

El menú principal agrupa sus ocho entradas por intención, y el orden es a propósito: `Install`,
`Update` y `Upgrade` primero (instalar y mantenerse al día), después `Configure models` y
`Grant MCP servers`, después `Status and diagnostics`, y por último `Uninstall` antes de `Exit`
— la entrada destructiva queda lejos de donde la navegación con flechas la podría tocar por
accidente.

Se maneja enteramente con el teclado: flechas o `j`/`k` para moverte, `enter` o `espacio` para elegir
(en la pantalla de selección de MCPs, cualquiera de los dos tilda o destilda un servidor), `d` para
borrar donde aplica, `esc` para volver a la pantalla anterior, `q` para salir. Si corrés `pegasus` sin
una terminal atrás (salida redirigida a un archivo o a una tubería), no hay menú que mostrar: imprime
la misma línea de uso que `pegasus --help` y termina con código de salida distinto de cero — por eso
un agente nunca debería invocarlo así (ver [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md)).

Al abrir el menú pueden aparecer, arriba de todo, hasta dos avisos independientes — separados a
propósito, porque cada uno se arregla distinto: uno local (esta instalación se hizo con una versión de
Pegasus más vieja que la que estás corriendo ahora → `Update`), y uno remoto (hay un release más nuevo
publicado que el binario que estás corriendo → `Upgrade`). El chequeo remoto corre en segundo plano,
no bloquea el menú, y falla en silencio ante cualquier problema de red.

Durante una instalación, la TUI muestra una barra de progreso con la unidad que se está procesando; al
terminar con éxito, la pantalla de resultado remata con un banner "PEGASUS HARNESS". Por debajo es la
misma instalación de siempre — llama al mismo motor que usar `pegasus` por línea de comandos — así que
nada de lo que sigue deja de aplicar si preferís este camino.

## Usar `pegasus` por línea de comandos

Además de la TUI, `pegasus` se usa por línea de comandos: cada comando toma flags explícitas, no hay
menú ni pantalla de espera, `--dry-run` te muestra el plan sin escribir nada, `--json` te da un reporte
que podés parsear en vez de prosa, y el código de salida es el contrato — `0` para éxito, distinto de
cero para cualquier otra cosa. Es la forma pensada para scripts, para reproducir la misma instalación
en varias máquinas, y para cualquiera que prefiera no abrir un menú. El resto de este manual describe,
comando por comando, lo que sigue.

## Instalar el payload en OpenCode

Con `pegasus` en el PATH, el comando que aplica el payload es:

```sh
pegasus install --cli opencode --dry-run --mcp <id>
```

`--dry-run` muestra el plan sin escribir nada; repetir el mismo comando sin ese flag lo aplica. Un servidor MCP no nombrado con `--mcp` no se instala — no hay `--confirm`/`--decline` como en v3, cada `install` nombra su selección entera. Podés repetir `--mcp` para pedir varios. Eso vale tal cual para la primera instalación; después no, y el cambio es deliberado: un `install` a secas sobre una instalación que ya tiene una selección registrada se rechaza antes de escribir nada, en vez de retirarla en silencio porque nadie repitió el flag. Para dejar esa selección como está, usá `pegasus update --cli opencode`; para revocarla a propósito, `--mcp none`. Las tres cosas —el rechazo, que no escriba nada al rechazar, y que la revocación deliberada vacíe de verdad la selección— las corre contra una instalación real `ManualSaysHowAnMcpSelectionIsRevokedOnPurposeTest` (`tests/test_manual_command_surface.py`).

Cada `--mcp` acepta dos grafías, y no piden lo mismo: `--mcp <id>` le pide a Pegasus que obtenga y administre ese servidor, y `--mcp <id>=<clave>` le pide sólo el contrato —la convención y los permisos— contra un servidor que tu instalación ya corre bajo esa clave, sin descargar ni configurar nada para ese id. Cómo se pasa de una a la otra, y qué pasa si esa clave choca con una que ya otorgaste, está en [Dar acceso a un MCP que vos mismo administrás](#dar-acceso-a-un-mcp-que-vos-mismo-administrás). Qué hace cada grafía con la instalación no se afirma acá: las corre contra una real `ManualSaysWhatTheTwoMcpSpellingsAskForTest` (`tests/test_manual_command_surface.py`), comparando qué queda configurado y qué permiso lleva cada agente.

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

Lo mismo se elige desde la TUI (`pegasus`, sin argumentos), en el menú principal → `Install` → elegí el CLI: antes del plan aparece la pantalla `Install · <CLI> · choose which mcp servers to install`, un casillero por cada servidor que esta release embarca y una fila `Continue` al final. Gobierna una sola cosa: cuáles de esos servidores son parte de la instalación. Abre mostrando el estado real de la máquina y no una lista vacía —todo lo que el journal registra como instalado abre tildado—, y eso incluye los servidores atados: uno que Pegasus no obtiene sino que usás contra una clave tuya (`--mcp id=<clave>`) está instalado igual, así que abre tildado, y su fila lo dice con el prefijo `bound to <clave>` delante de la descripción. Dos casilleros idénticos que significan cosas distintas serían una trampa: uno pide «instalá y administrá este servidor» y el otro «dame el contrato contra el que ya corro bajo esta clave».

Por eso continuar sin tocar nada reproduce el estado que ya tenías, en vez de retirar una parte: cada fila tildada se vuelve a emitir con la grafía con la que estaba registrada, `id=clave` para una atada y el nombre pelado para una que administra Pegasus. Destildar una fila es la única forma de pedir un retiro, y por eso siempre es un acto deliberado. Lo que esta pantalla no hace es cambiar quién administra un servidor: convertir uno atado en uno que Pegasus obtiene, o al revés, es trabajo de `Grant MCP servers` (más abajo), y acá una fila conserva su atadura la tildes o la destildes.

Si destildaste algo, lo que te salva es el plan que viene después: todavía no escribió nada, y lista bajo `Would retire, no longer asked for:` exactamente lo que ese `Continue` sacaría de la máquina. Leé esa sección antes de confirmar; si aparece algo que no querías sacar, `esc` vuelve atrás sin escribir y podés volver a tildarlo. Si la instalación tiene una ligadura sin resolver (`--mcp id=<clave>` con la clave nunca registrada), la pantalla muestra ese bloqueo en lugar de la lista, por el mismo motivo que `Grant MCP servers`: con ese estado sin resolver no hay fila que pueda reproducirse bien, y hay que resolverlo primero.

## Dar acceso a un MCP que vos mismo administrás

Pegasus renderiza cada agente con una base que niega todo (`{"*": false}`) más una lista de los servidores que él mismo instala. Un MCP que instalaste y administrás por tu cuenta (Sentry, Figma, o cualquier otro) queda fuera de esa lista aunque figure en tu `opencode.json`: OpenCode combina el bloque de permisos propio del agente al final, así que si Pegasus no le abre la puerta a esa clave, ningún agente puede usarla, sin importar qué diga tu configuración general.

Si ya administrás tu propia clave `jira` con `mcp grant` —que alcanza a **todos** los agentes que la release embarca, sin excepción y sin que el número cambie la regla: hoy son **16 agentes**— y más adelante un `install`/`update` selecciona el `jira` que Pegasus embarca —que sólo alcanza a los agentes que su propio descriptor nombra, hoy **11 agentes**, los mismos que llevan Context7—, la colisión no aborta nada: `grant_mcp` descarta en silencio el grant que venías arrastrando, por considerarlo redundante, y tu alcance se achica de todos los agentes a ese subconjunto sin más aviso que el `grant_warnings` del report. Las dos cifras no se retipean acá: las deriva del árbol `GrantMcpReachesEveryAgentTest` (`tests/test_manual_figures.py`), que además corre el grant de verdad para comprobar que «todos» sigue siendo todos, y falla el día que alguna deje de coincidir.

`pegasus mcp` es la palanca para eso. A diferencia de los MCPs que Pegasus instala, acá no hay elección por agente: la clave se otorga a todos los agentes por igual, porque hacerlo agente por agente volvería tediosa la tarea de sumar un MCP más.

```sh
pegasus mcp grant --cli opencode sentry-mcp
pegasus mcp list --cli opencode
pegasus mcp revoke --cli opencode sentry-mcp
```

`grant` y `revoke` aceptan más de una clave en el mismo comando (`pegasus mcp grant --cli opencode sentry-mcp linear figma`, no una lista separada por comas): cada clave se valida antes de otorgar nada, así que una clave mal tipeada en el medio del lote rechaza el lote entero y no otorga ni una — nunca deja la mitad otorgada. Esto es también lo que evita que asignar varias claves dispare varios renders completos y varias generaciones de snapshot por una intención que era una sola. `grant` rechaza una clave que tu propia configuración de OpenCode no declara bajo `mcp` — nombra ahí mismo cuáles sí declara, para que un error de tipeo no termine en un permiso que nadie nota que falta. `revoke` sobre una clave que nunca otorgaste no es un error: informa que ya estaba en ese estado y sale en `0`. `list` muestra lo que está otorgado ahora, y de las claves que tu configuración declara y todavía no otorgaste, cuáles `grant` aceptaría tal como está la instalación — nunca una que `grant` fuera a rechazar. Una clave declarada que Pegasus ya alcanza por agente (un servidor propio de esta instalación, o una clave ya ligada) se muestra aparte, marcada como ya cubierta, en vez de desaparecer del listado sin explicación. `list` no escribe nada: lee el journal y tu configuración, y deja `opencode.json` exactamente como estaba.

`pegasus mcp grant` y `pegasus mcp revoke` reaplican la configuración renderizada al terminar — igual que `pegasus install` — así que el cambio ya queda escrito en `opencode.json`. Cuál de los subcomandos escribe y cuál no, no se afirma acá de memoria: lo mide `ManualSaysWhichMcpSubcommandsRewriteTheConfigurationTest` (`tests/test_manual_command_surface.py`), corriendo cada uno contra una instalación real y comparando el archivo renderizado byte a byte de un lado y del otro de la llamada. Como con cualquier cambio a los agentes, hace falta reiniciar OpenCode para que lo lea: sigue leyendo la configuración de agentes una sola vez, al arrancar. `pegasus update --cli opencode` reaplica las claves otorgadas junto con el resto de la selección, sin flags.

Lo mismo está disponible desde la TUI (`pegasus`, sin argumentos), en el menú principal → `Grant MCP servers` → elegí el CLI. La pantalla lista las claves que `mcp list` reporta como `available` para esa instalación, cada una tildada o no según si ya está otorgada; espacio o enter la tilda o destilda, y `Continue` aplica de una sola vez todo lo otorgado y todo lo revocado — y sólo cuenta como aplicado lo que su propio llamado efectivamente logró, nunca lo pedido sin más si algo se rechazó mientras tanto. Si no hay ningún servidor propio para mostrar, la pantalla explica cuál de dos motivos es: no instalaste ninguno todavía (instalalo en OpenCode como siempre lo harías, y volvé acá a otorgarlo), o ya instalaste uno pero Pegasus ya lo alcanza por agente y nombra cuál — ahí no hay nada para hacer, no es que la detección haya fallado. Si la instalación tiene una ligadura sin resolver (`--mcp id=<clave>` sin la clave nunca registrada), la pantalla lo dice en vez de listar nada: mientras eso siga así, `grant`/`revoke` se niegan para cualquier clave, no sólo la ligada, y hace falta resolverlo primero (ver más arriba). El resultado avisa el mismo reinicio que ya se menciona arriba.

Si más adelante un `install` liga un servidor propio de Pegasus (`--mcp id=<clave>`) bajo la misma cadena que una clave que ya habías otorgado, esa clave otorgada queda redundante y el `install` la descarta en vez de fallar — el servidor sigue siendo alcanzable a través de los agentes que ahora lo declaran. El comando avisa qué clave descartó; si no era lo que querías, volvé a otorgarla con `pegasus mcp grant`.

## Dar acceso a un directorio de trabajo propio

OpenCode pregunta por un permiso separado, `external_directory`, apenas una herramienta de archivo o `bash` apunta a algo fuera del worktree del proyecto. Cada agente que Pegasus instala ya trae la excepción que necesita para leer sus propias skills, pero un directorio que vos necesitás — un worktree enlazado, un árbol de scratch fuera del repo — es un dato que Pegasus no puede conocer de antemano, y no hay forma de agregarlo a mano: Pegasus reclama la entrada completa de cada agente en `opencode.json`, así que una excepción escrita a mano la pisa el próximo `install`/`update`.

```sh
pegasus directory grant --cli opencode /home/vos/worktrees/otro-repo
pegasus directory revoke --cli opencode /home/vos/worktrees/otro-repo
```

`grant` acepta cualquier ruta absoluta que no sea la raíz del filesystem (`/`), no contenga un metacarácter de glob (`*`, `?`, `[`, `]`), y no sea el directorio de configuración de OpenCode, el directorio de datos propio de Pegasus (donde vive su journal), ni un ancestro de cualquiera de los dos. El de configuración guarda tus propios servidores; el de datos guarda el registro que `uninstall` usa para decidir qué borrar, así que darle escritura a un agente ahí equivaldría a dejarlo decidir qué se borra en la próxima desinstalación. Fuera de esas restricciones, una ruta relativa o con `..` también se rechaza; el resto se acepta, incluida una ruta fuera de tu home. La ruta se normaliza antes de guardarse (una barra final o `//` repetidas colapsan a la misma forma), así que `grant`/`revoke` con distinta grafía de la misma ruta se reconocen entre sí. `revoke` sobre una ruta que nunca otorgaste no es un error: informa que ya estaba en ese estado y sale en `0`. Igual que `mcp grant`/`mcp revoke`, los dos aceptan más de una ruta en el mismo comando (rutas repetidas, nunca separadas por comas): cada una se valida antes de otorgar o revocar nada, así que una ruta inválida en el medio del lote rechaza el lote entero, nombrándola, y no toca el disco — la alternativa, un lote a medio aplicar, dejaría la instalación en un estado que no corresponde ni a lo que había antes ni a lo que se pidió.

A diferencia de un MCP propio, un directorio otorgado alcanza a **todo** agente, primario o sub-agente por igual — no hay recorte por agente que preservar, así que no hace falta. Los dos reaplican la configuración renderizada al terminar, igual que `pegasus mcp grant`, así que el cambio ya queda escrito en `opencode.json` y sobrevive a cada `install`/`update` posterior sin que haga falta repetirlo. Como con cualquier cambio a los agentes, hace falta reiniciar OpenCode para que lo lea.

Un directorio que otorgás nunca se renderizó como una pregunta, pero desde qué línea de base dejó de serlo cambió: ya no es la línea de base `"*": "ask"` la que esa entrada le gana por escribirse después. Pegasus renderiza `external_directory` con línea de base `"*": "allow"` — todo agente que declara una herramienta de archivo o `bash` puede salir del worktree sin que nadie apruebe nada, otorgado el directorio o no. Esta es una decisión de producto deliberada, expuesta —no motivada— por un bug abierto de OpenCode (`anomalyco/opencode#39112`): a dos niveles de sub-agente, el pedido de `external_directory` no aparece en ninguna pantalla de la TUI y la herramienta se cuelga para siempre, sin límite de tiempo, porque la vista que lista pedidos pendientes sólo mira un nivel de la sesión. Como Pegasus encadena sub-agentes hasta profundidad 10, esa cadena es habitual, no una rareza, así que la línea de base pasó de preguntar a permitir para no colgarse nunca — a costa de dejar de preguntar también en las dos profundidades donde sí preguntaba bien.

Mientras la línea de base sea `"allow"`, el otorgamiento queda **dormido, no inútil**: el comando sigue existiendo, sigue quedando en el journal, y sigue escribiendo su propia entrada, `"/home/vos/worktrees/otro-repo/*": "allow"`, con el mismo valor que la línea de base, `"*": "allow"` — así que hoy no cambia nada que esa línea de base no cambiara ya. Eso no es motivo para revocar lo que ya otorgaste: que `#39112` se resuelva río arriba no vuelve la línea de base a `"*": "ask"` por sí solo — habilitar `external_directory` por default es una decisión de producto asentada, no condicionada a ese arreglo. Si la línea de base cambiara alguna vez por otra razón, cada entrada otorgada recuperaría de una su sentido completo, sin que haga falta volver a correr `directory grant`; por eso el otorgamiento se sigue escribiendo aunque hoy sea dormido, no por anticipar una reversión pautada. Lo único que esa línea de base no alcanza, otorgado o no, es un puñado fijo de directorios que Pegasus deniega en su grafía canónica: cualquier `.ssh/`, `.aws/`, `.credentials/`, `.config/gh/` o `secrets/`, escritos después de cualquier entrada otorgada para que ganen incluso si alguien otorgara justo esa ruta — otorgar no puede destrabarlos. La entrada que se cita acá, y la lista de directorios siempre denegados, salen del `opencode.json` real: la deriva `ManualSaysHowAGrantedDirectoryIsRenderedTest` (`tests/test_manual_command_surface.py`).

Sé honesto con vos mismo sobre qué es esto y qué no es: un piso contra el agente que entra a uno de esos cinco directorios **por accidente**, no una frontera contra el que quiere llegar ahí a propósito. El match es sobre el string literal del path — ni el runtime ni este piso llaman `realpath` — así que un symlink, un bind mount, o una variable de entorno que un programa invocado por `bash` respeta (`GH_CONFIG_DIR`, `AWS_SHARED_CREDENTIALS_FILE`) atraviesan el piso sin tocarlo, y un agente que ya tiene `bash` bajo esta misma línea de base `allow` puede construir esa vuelta él mismo. Y todo lo que el piso no puede alcanzar por construcción — un `*.pem`, un `*.key`, un `.env` que viva fuera de esos cinco directorios, que es la mayoría de los lugares donde un archivo puede vivir — queda alcanzable de verdad para cualquier agente con una herramienta de archivo, no meramente "sin guardia en abstracto".

Si la ruta que otorgás cae bajo uno de esos cinco directorios, `directory grant` no la rechaza — sigue otorgando y sigue registrando, igual que cualquier otra ruta — pero el reporte incluye un aviso explicando que esa entrada nunca va a tener efecto, porque el piso se escribe después de cualquier concesión y siempre gana la resolución del runtime. Esto no es el mismo caso **dormido** que el párrafo anterior: un otorgamiento ordinario recupera su sentido completo el día que la línea de base vuelva a `"ask"`; uno que el piso alcanza **nunca** lo recupera, porque el piso se escribe al final sin importar cuál sea la línea de base. El aviso se calcula comparando la ruta contra las mismas cinco entradas de `EXTERNAL_DIRECTORY_DENY_FLOOR`, con la misma semántica de comodín que usa el runtime — no una comparación aproximada por nombre de directorio.

## Usarlo todos los días

1. Abrí OpenCode dentro del repositorio en el que vas a trabajar.
2. Pedí lo que necesitás con tus palabras. El orquestador elige la ruta: una consulta se responde sin tocar nada, un cambio trivial y ya entendido se hace directo, y la mayoría de los cambios comunes van por FTD sin que tengas que pedirlo.
3. En FTD, el agente cierra el alcance, te pide una sola confirmación antes de escribir y lleva un record en `docs/ftd/`. El FTD que crea esa carpeta te avisa una sola vez; si no querés versionarla, agregá `docs/ftd/` a `.gitignore`, o a `.git/info/exclude` si tampoco querés versionar la exclusión.
4. SDD aparece cuando hace falta: el orquestador lo propone si hay que fijar antes del código un contrato o una decisión que va a revisar alguien que no está en la implementación, o una spec contra la que otros van a construir, y entra sólo si aceptás. También podés pedirlo vos (`sdd-init`, `sdd-new` o `sdd-ff`): completás el pre-chequeo de sesión, explore, propuesta, spec, diseño y tareas aclaran el cambio antes de `sdd-apply`, y cerrás con `sdd-verify`, la única autoridad para declarar listo para archivar un cambio SDD.

Qué ruta toma cada pedido lo decide [flow-applicability.md](src/pegasus/content/skills/_shared/flow-applicability.md), y cómo corre un FTD, [ftd-procedure.md](src/pegasus/content/skills/_shared/ftd-procedure.md).

Los comandos distribuidos son `sdd-init`, `sdd-new`, `sdd-ff`, `sdd-continue`, `sdd-apply`, `sdd-status`, `sdd-verify`, `sdd-archive`, `sdd-onboard`, `sdd-explore`, además de `context-load`, `context-save`, `handoff-load`, `handoff-save`, `skill-creator` y `skill-registry`. Podés leer su contenido en `~/.config/opencode/commands/` antes de usarlos.

## Elegir proveedor, modelo y esfuerzo

Pegasus distribuye roles, no credenciales ni modelos: ningún agente trae uno asignado por defecto. En el primer arranque, ejecutá `/connect` dentro de OpenCode para configurar las credenciales del proveedor, y `/models` para elegir el modelo que querés usar de forma general. Esas dos decisiones son tuyas y OpenCode las guarda en su propia configuración; Pegasus no las lee ni las reproduce.

Para asignar un modelo puntual a un agente, Pegasus tiene su propio comando, separado del `/models` de OpenCode. Lo acepta **todo** agente que esta release embarca —el orquestador, `king-pegasus` y los especialistas sin fase incluidos—, sin excepción y sin que el número cambie la regla: hoy son **16 agentes**. Ni la regla ni la cifra se retipean acá: las deriva del árbol `EveryShippedAgentAcceptsAModelAssignmentTest` (`tests/test_manual_figures.py`), que además le pide una asignación a cada agente embarcado para comprobar que ninguno la rechaza. Se usa así:

```sh
pegasus models set --cli opencode --assign sdd-apply=anthropic/claude-sonnet-5 --effort sdd-apply=high
pegasus models list --cli opencode
pegasus models unset --cli opencode --agent sdd-apply
```

`--assign` y `--effort` se repiten, cada uno por su cuenta, para asignar varios agentes en un solo comando: `--assign sdd-apply=anthropic/claude-sonnet-5 --assign king-pegasus=anthropic/claude-opus-5 --effort king-pegasus=high` graba las dos asignaciones y reaplica una sola vez, en vez de correr `models set` dos veces y pagar dos renders completos y dos generaciones de snapshot por una intención que era una sola. Cada flag nombra el agente al que pertenece (`AGENT=PROVIDOR/MODELO`, `AGENT=NIVEL`) en vez de emparejarse por posición entre dos flags repetidos por separado, porque esa relación implícita no la valida `argparse` y un desalineamiento pasaría en silencio. `models unset --agent` también es repetible, para sacar varias asignaciones en un solo comando. Si un ítem del lote es inválido —un agente que esta release no ofrece, un `PROVIDOR/MODELO` mal escrito, un `--effort` para un agente que ningún `--assign` nombró—, el comando entero se rechaza, nombra cuál fue y no graba nada: ni una asignación a medias.

`models set` escribe la asignación en la configuración de OpenCode en el mismo comando, y `models unset` la saca igual: no hay un segundo paso que acordarse de correr. Por eso los dos rechazan una CLI que no tenga nada instalado, con el mismo mensaje que ya dan `pegasus mcp grant` y `pegasus directory grant`: no hay configuración que reaplicar. Lo único que queda después es reiniciar OpenCode, que lee los prompts de los agentes una sola vez al arrancar. Si una asignación quedó guardada sin renderizar —por ejemplo, porque el proveedor no estaba disponible en el momento de guardarla—, cualquier comando que reaplique la configuración entera se la lleva con él: `pegasus install --cli opencode`, `pegasus update --cli opencode`, `pegasus mcp grant` y `pegasus directory grant`. Todo eso lo corre contra una instalación real `ManualSaysWhenAModelAssignmentReachesTheConfigurationTest` (`tests/test_manual_command_surface.py`), leyendo el archivo renderizado de un lado y del otro de cada llamado. No pongas tokens ni credenciales en el repo, en prompts, ni en comandos versionados.

## Verificar el estado

```sh
pegasus doctor
```

Reporta qué CLIs anfitrionas detecta y qué drift hay entre lo instalado y lo que el contenido actual generaría. No reemplaza una prueba de comportamiento.

Para chequear además que cada servidor MCP instalado arranca y contesta el handshake de MCP:

```sh
pegasus doctor --start-mcp-servers
```

Tiene sentido correrlo después de instalar servidores MCP, o cuando un cliente reporta que uno no conecta. A diferencia de `doctor` a secas, este flag ejecuta los comandos que la configuración tiene guardados — por eso no es el comportamiento por defecto.

Por cada servidor que este flag arranca informa uno de estos estados: `ok` (contestó el handshake), `timeout` (arrancó pero nunca contestó), `exited` (terminó antes de contestar), `invalid` (contestó algo que no es una respuesta MCP válida), `not-found` (no se pudo arrancar), `unreadable` (no se pudo leer la configuración de donde sale el comando) o `missing` (esa configuración ya no tiene la entrada que el journal reclama). Un servidor configurado como remoto no se arranca y se informa `remote`. Y uno atado a una clave que administrás vos (`--mcp id=<clave>`) tampoco aparece en esa lista: se informa aparte, con estado `bound`, y eso lo dice también un `pegasus doctor` sin el flag, porque no hay proceso que arrancar — es el estado normal de una instalación así, no una falla. Ninguno de esos estados se retipea acá: los deriva del árbol `ManualSaysEveryStatusDoctorCanReportTest` (`tests/test_manual_command_surface.py`), que además instala un servidor atado y uno remoto de verdad para comprobar dónde cae cada uno.

`pegasus repair --cli opencode` saca dos cosas que `doctor` sólo nombra, con `--dry-run` disponible para ver antes qué se va a remover: las entradas de `directories_quarantined` -- un `granted_directories` editado a mano en el journal que no pasó la validación y por eso no le concede nada a ningún agente -- y los directorios vacíos que `doctor` reporta bajo `unprunable_empty_directories`, de una instalación anterior a 5.28.0 que la poda automática nunca puede alcanzar. Toma un snapshot del journal antes de escribir, así que `pegasus restore` deshace la parte del journal igual que deshace cualquier otro comando; un directorio vacío borrado no se restaura -- no hay nada que recuperar más allá de un `mkdir`. Si `doctor` reporta `directories_not_walked`, hay un subárbol detrás de un symlink que ni `doctor` ni `repair` pudieron recorrer, y `repair` lo dice en su propio reporte en vez de sugerir que ahí no queda nada.

## Mantener Pegasus al día

Son dos actualizaciones distintas y conviene no confundirlas: `pegasus update --cli opencode` reaplica en OpenCode la selección que esa instalación ya tiene registrada, y `pegasus upgrade` no toca ninguna instalación — reemplaza el binario `pegasus` en sí. Para saber desde qué versión partís, `pegasus -V` (o `pegasus --version`) la contesta sin abrir tu home, sin leer el journal y sin resolver ningún adapter: es la versión del binario y no la de ninguna instalación suya, así que sigue contestando en una máquina donde la instalación esté rota, que es justo cuando hace falta.

```sh
pegasus upgrade --dry-run
pegasus upgrade
```

No lleva `--cli` porque no se trata de ninguna instalación puntual. Se niega antes de bajar un solo byte si no está corriendo desde un ejecutable instalado, si el destino no es escribible, si el archivo que hay ahí es de otra persona, o si no llega a la red para averiguar cuál es la última versión publicada. Recién después baja el checksum y el binario, lo verifica contra ese checksum, y lo pone en su lugar con un único rename atómico: un checksum que no coincide o una escritura que falla dejan intacto el binario con el que arrancaste, así que nunca hay un momento sin un `pegasus` funcionando en disco. Estar ya en la última versión publicada no es un error — lo informa y sale en `0`. Después hace falta reiniciar Pegasus: el proceso que acaba de hacer el upgrade sigue siendo, en memoria, la versión vieja.

Lo mismo está en la TUI (`pegasus`, sin argumentos), en el menú principal → `Upgrade`. Al abrir el menú, si hay un release más nuevo publicado que el binario que estás corriendo, el aviso aparece arriba de todo; ese chequeo corre en segundo plano, no bloquea el menú, y falla en silencio ante cualquier problema de red.

## Deshacer

- `pegasus restore [generación]` vuelve al estado exacto anterior a un comando (o a una generación puntual del historial de snapshots). `pegasus restore --list` muestra qué generaciones existen todavía -- número, cuándo se tomaron, qué comando las produjo y cuánto tocarían -- para elegir una sin adivinar.
- `pegasus uninstall --cli opencode` retira solo lo que el journal reclama como propio.

El journal vive en `$XDG_DATA_HOME/pegasus-harness/journal-v4.json` (o `~/.local/share/pegasus-harness/journal-v4.json`), en un directorio `0700` con el archivo en `0600`. Lo que decide qué se toca es **el journal y nada más**: un archivo que Pegasus nunca creó no se toca nunca, y uno que el journal reclama se retira aunque vos lo hayas editado después. Nunca uses `restore` ni `uninstall` para borrar configuración que ya era tuya.

Una edición tuya sobre un archivo que Pegasus instaló no sobrevive: `install` y `update` la reescriben con la versión del release, y `uninstall` la borra sin aviso equivalente al `overwritten` que sí te dan los otros dos. Lo que te recupera es `pegasus restore`, con veinte generaciones de historial y no más. El motivo de esa política, los dos huecos del aviso y qué hacer en cada caso están en [docs/arquitectura/arquitectura.md#limitaciones-aceptadas](docs/arquitectura/arquitectura.md#limitaciones-aceptadas).

## Próximo paso

- Para el recorrido completo de instalación: [INSTALL.md](INSTALL.md).
- Para instalación asistida por un agente: [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md).
- Para la arquitectura y las decisiones de diseño: [docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md).
