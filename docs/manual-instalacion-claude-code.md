# Instalacion manual en Claude Code

Este manual explica como integrar Pegasus a mano y sin plugins, para casos
avanzados. No reemplaza el instalador automatico del release. Para instalar algo
estable, trabaje primero con un archivo de GitHub Release o un checkout del tag
semantico publicado, y verifique su checksum. Hacerlo a mano implica revisar,
integrar y mantener cada archivo. No lo haga desde una rama mutable.

## Preparacion segura

1. Trabaje desde una copia de un release o tag verificado.
2. Antes de modificar cada destino, haga un respaldo y anote los archivos que
   va creando.
3. Integre instrucciones y configuracion de forma puntual. No pise `CLAUDE.md`,
   `.mcp.json` ni directorios existentes completos.
4. No deje tokens, claves ni credenciales en archivos rastreados, ejemplos o
   `.mcp.json`. Use el entorno de ejecucion o el gestor de secretos que admita
   su organizacion.
5. Reinicie Claude Code despues de cambiar skills, instrucciones, comandos,
   agentes o MCP para que vuelva a descubrir la configuracion.

## Alcance de la instalacion

| Alcance | Destino recomendado | Cuando usarlo |
| --- | --- | --- |
| Usuario global | `~/.claude/` | La habilidad o instruccion debe estar disponible para todos los proyectos de una persona. |
| Proyecto local | `<repositorio>/.claude/`, `<repositorio>/CLAUDE.md` y `<repositorio>/.mcp.json` | La configuracion debe quedar limitada al repositorio, revisarse con el equipo o variar por proyecto. |

Para skills, la estructura es `skills/<nombre>/SKILL.md`: use
`~/.claude/skills/<nombre>/SKILL.md` para alcance global y
`<repositorio>/.claude/skills/<nombre>/SKILL.md` para alcance local. Use
`~/.claude/CLAUDE.md` para instrucciones de usuario y el `CLAUDE.md` en la raiz
del repositorio para instrucciones del proyecto. Los comandos y agentes que
usted cree deliberadamente pueden vivir en `commands/<nombre>.md` y
`agents/<nombre>.md` bajo el alcance correspondiente. Esos no vienen como
assets nativos de Claude Code en esta distribucion.

## Lo que Pegasus distribuye para Claude Code

Para Claude Code, Pegasus trae nativamente solo esto:

| Asset | Origen | Uso manual |
| --- | --- | --- |
| Skills canonicas | `source/core/skills/` | Copiar cada directorio completo a `~/.claude/skills/` o `.claude/skills/`. |
| Adaptador de instrucciones | `source/adapters/claude-code/CLAUDE.md` | Fusionar sus reglas pertinentes en el `CLAUDE.md` global o del proyecto. |

Pegasus no trae comandos de Claude Code, agentes de Claude Code ni una
configuracion MCP de Claude Code. Tampoco trae plugins para Claude Code, y este
manual no recomienda usarlos. Los comandos de
`source/opencode/commands/`, los agentes de `source/agents/`, los prompts SDD y
la configuracion de `source/opencode/` son assets de OpenCode; no los copie como
si fueran compatibles sin revisarlos.

Las skills canonicas actuales son `laravel-security` y
`skill-versiones-estandar-asi`, con sus referencias. Copie el directorio entero
de cada una. La skill de versiones ASI es politica organizacional privada:
instalela solo con autorizacion explicita de esa organizacion.

## Integracion manual

### Skills e instrucciones

Conserve exactamente el nombre `SKILL.md` y la jerarquia de cada skill. Despues
de reiniciar Claude Code, invoque o pida la skill segun su forma de trabajo y
confirme que puede leer sus referencias locales.

Abra `source/adapters/claude-code/CLAUDE.md` y fusione solo lo que corresponda.
El adaptador deja claro que las skills canonicas son la fuente de verdad,
prohibe plugins de Pegasus para Claude Code y exige que las credenciales queden
fuera de instrucciones y skills. No pise instrucciones del usuario o del
proyecto que no sean de Pegasus.

### Comandos y agentes creados por el usuario

Si necesita un equivalente de un comando o agente de OpenCode, cree su propio
archivo en `commands/` o `agents/` y adapte el contenido despues de revisarlo.
No hay conversion automatica ni compatibilidad garantizada: los comandos de
Pegasus para OpenCode pueden nombrar `pegasus-orchestrator`, usar el modelo de
permisos, la herramienta `task` o rutas `{file:...}` de OpenCode. Mantenga el
mapeo chico, deje anotado para que sirve y pruebe cada archivo por separado antes
de sumar mas componentes.

### MCP por proyecto o usuario

Para un MCP compartido por un proyecto, use `<repositorio>/.mcp.json`. Claude
Code tambien ofrece `claude mcp add` como asistente interactivo y
`claude mcp add-json` para agregar una definicion JSON; seleccione el alcance
de usuario o proyecto segun el servicio y el riesgo. En alcance de proyecto el
archivo queda para revision del equipo, asi que nunca puede llevar secretos.

Una entrada `stdio` de `.mcp.json` describe un servidor con `command`, `args` y,
si hace falta, `env`. Este es un ejemplo sin secretos:

```json
{
  "mcpServers": {
    "servidor-confiable": {
      "command": "comando-del-servidor",
      "args": ["--stdio"],
      "env": {
        "NIVEL_LOG": "warn"
      }
    }
  }
}
```

Instale y active solo servidores confiables. Antes revise el binario, sus
argumentos, origen, permisos y comportamiento de red. Los secretos van por
variables de entorno del proceso o mediante una referencia del gestor de
secretos, nunca escritos en `.mcp.json`. Si un servidor necesita una variable
secreta, configurela fuera del repositorio y valide su nombre y mecanismo antes
de activar el MCP.

## Verificacion

- [ ] El origen es un tag o release verificado y existen respaldos de los
  archivos que se cambiaron.
- [ ] Cada skill conserva `SKILL.md`, sus referencias y la ubicacion elegida
  coincide con el alcance deseado.
- [ ] `CLAUDE.md` conserva las instrucciones preexistentes y contiene solo las
  reglas de Pegasus que se decidieron adoptar.
- [ ] Cualquier comando o agente creado localmente fue adaptado y probado; no
  se asumio compatibilidad directa con OpenCode.
- [ ] `.mcp.json` es JSON valido, los servidores habilitados son confiables y
  no incluye tokens ni otros secretos.
- [ ] Claude Code se reinicio y descubre las skills, instrucciones y MCP sin
  errores.

## Reversion

Cierre Claude Code. Elimine solo los archivos anotados en su lista de cambios y
restaure los respaldos correspondientes. Para instrucciones, comandos o agentes
integrados en archivos existentes, retire solo el bloque agregado. Para MCP,
elimine solo el servidor de `mcpServers` que incorporo; no borre `.mcp.json` ni
directorios compartidos si tienen configuracion ajena. Reinicie Claude Code y
confirme que vuelve a operar como antes.
