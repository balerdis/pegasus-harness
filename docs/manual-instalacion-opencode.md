# Instalacion manual en OpenCode

Este manual es para cuando necesita sumar partes de Pegasus de forma selectiva
y despues mantenerlas usted. Para trabajar estable, baje el archivo de un
GitHub Release o haga checkout del tag semantico publicado, y verifique el
checksum. No trabaje desde la punta de una rama: se mueve y no sirve como fuente
reproducible. Esto no reemplaza al instalador; es una alternativa para uso
avanzado.

## Preparacion segura

1. Trabaje desde un tag o release verificado, nunca desde la punta de una rama.
2. Antes de tocar cada destino, haga un respaldo con fecha y anote los archivos
   que va agregando.
3. Revise el origen y fusione solo la seccion o el archivo que eligio. No pise
   un `opencode.json` completo ni un directorio compartido.
4. No deje claves, tokens ni credenciales en archivos versionados, ejemplos o
   capturas. Use las variables de entorno del proceso o el gestor de secretos
   de la organizacion.
5. Cierre y reinicie OpenCode despues de cambiar configuracion, skills, agentes
   o comandos. OpenCode los carga al iniciar.

## Alcance de la instalacion

| Alcance | Destino recomendado | Cuando usarlo |
| --- | --- | --- |
| Usuario global | `~/.config/opencode/` | La capacidad debe estar disponible en todos los proyectos de una persona. |
| Proyecto local | `<repositorio>/.opencode/` | La capacidad pertenece al repositorio, debe revisarse junto con el codigo o no debe afectar otros proyectos. |

Para el alcance global, use `~/.config/opencode/skills/<nombre>/SKILL.md`,
`~/.config/opencode/commands/<nombre>.md` y
`~/.config/opencode/agents/<nombre>.md`. Para el alcance local, use las rutas
equivalentes bajo `.opencode/`. OpenCode tambien acepta las variantes singulares
`skill`, `command` y `agent`; siga la convencion que ya existe en el destino y
no mezcle directorios porque si. La configuracion local puede estar en
`opencode.json`, `opencode.jsonc` o `.opencode/opencode.json`; la global es
`~/.config/opencode/opencode.json`. La configuracion local prevalece sobre la
global al combinarse.

## Que distribuye Pegasus

Antes de copiar, revise estos origenes en el checkout del release:

| Componente | Origen distribuido | Destino manual |
| --- | --- | --- |
| Skills canonicas, compartidas entre clientes | `source/core/skills/` | `skills/` del alcance elegido, preservando cada directorio y sus referencias. |
| Skills especificas de OpenCode | `source/opencode/skills/` | `skills/` del alcance elegido, solo las que haya revisado. |
| Comandos Pegasus | `source/opencode/commands/` | `commands/`, con el nombre de archivo como nombre del comando. |
| Agentes e instrucciones | `source/agents/` y `source/opencode/AGENTS.md` | `agents/` y el archivo de instrucciones que corresponda al alcance elegido. |
| Prompts referenciados por agentes | `source/opencode/prompts/` | `prompts/`, manteniendo su estructura relativa. |
| Plantilla y extensiones de OpenCode | `source/opencode/opencode.json` y `source/opencode/plugins/` | Extraiga solo entradas compatibles; no copie la plantilla completa. |

Las skills canonicas actuales son `laravel-security` y
`skill-versiones-estandar-asi`, incluidas sus referencias. La segunda contiene
politica organizacional privada: instalela solo si esa organizacion la autorizo.
La carpeta `source/opencode/skills/` contiene el conjunto adicional de Pegasus
para OpenCode. Copie un directorio de skill completo, no solo `SKILL.md`, para
no perder referencias, plantillas o archivos auxiliares.

## Integracion selectiva

### Skills y comandos

Copie los directorios de `source/core/skills/` y, si los necesita, de
`source/opencode/skills/` al directorio `skills` elegido. Cada skill debe
conservar la forma `<nombre>/SKILL.md`. Para comandos, copie archivos concretos
de `source/opencode/commands/` a `commands/`; por ejemplo,
`sdd-init.md` conserva su nombre de comando. Antes de habilitarlo, revise el
frontmatter: algunos comandos nombran `pegasus-orchestrator` y necesitan que
ese agente este configurado.

### Agentes, instrucciones y prompts

`source/agents/pegasus-orchestrator.md` y `source/agents/pegasus-AGENTS.md`
son archivos de instrucciones, no una definicion completa de agente por si
solos. La definicion de `pegasus-orchestrator` se encuentra en
`source/opencode/opencode.json` y referencia esos archivos y los prompts SDD.
Si va a habilitar ese agente, copie tambien `source/opencode/prompts/sdd/` y
adapte las rutas `{file:...}` para que sean relativas al `opencode.json` que
esta editando.

No active todos los agentes o plugins de la plantilla porque si. Elija los que
realmente necesita, mantenga permisos restrictivos y revise cada herramienta,
modelo y ruta de prompt. El instalador controlado arma una configuracion mas
chica: registra `skills.paths: ["./skills"]`, deja solo el MCP de Codebase
Memory y elimina proveedores. Esa separacion evita llevarse integraciones o
secretos del usuario.

### Configuracion y MCP

`source/opencode/opencode.json` es una plantilla de activacion saneada; no es
una configuracion para pisar. Mantenga `"$schema":
"https://opencode.ai/config.json"` en su configuracion y fusione un bloque por
vez. Por ejemplo, una entrada local de MCP valida queda asi:

```json
{
  "mcp": {
    "servidor-confiable": {
      "type": "local",
      "command": ["comando-del-servidor", "--stdio"],
      "enabled": true,
      "environment": {
        "NIVEL_LOG": "warn"
      }
    }
  }
}
```

Para un MCP remoto, use `type: "remote"`, `url` y, cuando corresponda,
cabeceras con referencias de entorno como `"Bearer {env:MI_TOKEN}"`; no escriba
el token. En OpenCode `command` siempre es una lista de cadenas y `type` es
obligatorio. La plantilla contiene ejemplos reales de MCP locales y remotos,
pero muchos son opcionales y dependen de binarios, endpoints o autenticacion que
Pegasus no instala manualmente.

Active solo servidores confiables. Antes de reiniciar, revise el ejecutable,
sus argumentos, procedencia, permisos de red y directorio de trabajo. Los
secretos van en el entorno de ejecucion o en un gestor de secretos, nunca en
`opencode.json`, archivos `.env` rastreados ni ejemplos. Los plugins de
`source/opencode/plugins/` son opcionales, exclusivos de OpenCode y pueden
pedir contratos de entorno adicionales; no hacen falta para instalar skills o
comandos.

## Verificacion

- [ ] El checkout procede de un tag o release verificado y se registraron los
  archivos modificados.
- [ ] Cada skill instalada conserva `SKILL.md` y sus archivos referenciados.
- [ ] Los comandos que apuntan a `pegasus-orchestrator` tienen un agente y
  prompts accesibles.
- [ ] `opencode.json` sigue siendo JSON valido y sus referencias `{file:...}`
  resuelven desde su ubicacion.
- [ ] Cada MCP habilitado usa un comando o URL revisado y no contiene secretos.
- [ ] OpenCode se cerro y reinicio; las skills, comandos y agentes esperados se
  descubren sin errores de configuracion.

## Reversion

Cierre OpenCode. Saque solo los archivos anotados en su lista de cambios y
restaure cada respaldo hecho antes de copiar. Si agrego una entrada al objeto
`mcp`, `agent`, `command`, `plugin` o `skills` de una configuracion existente,
retire solo esa entrada: no restaure ni borre directorios compartidos completos.
Reinicie OpenCode y confirme que vuelve a iniciar con la configuracion anterior.
