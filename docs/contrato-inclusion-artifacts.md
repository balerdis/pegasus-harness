# Contrato de inclusion de artifacts Pegasus

Este documento fija la decision de distribucion de Pegasus. Pegasus se suma a una instalacion existente de OpenCode o Claude Code: no instala ni reemplaza el cliente anfitrion, y tampoco borra, mueve o sobreescribe artifacts del usuario.

Toda implementacion y todo release futuro tienen que respetar este contrato. Si una necesidad no entra en estas reglas, se decide antes de distribuirla.

## Modelo aprobado

Pegasus se distribuye de forma aditiva. La instalacion reconoce lo que ya existe y agrega solamente lo que corresponde al release seleccionado.

| Tema | Decision |
| --- | --- |
| Cliente anfitrion | OpenCode o Claude Code ya instalado. Pegasus no lo instala, actualiza, reemplaza ni desinstala. |
| Artifacts del usuario | No se borran, mueven ni sobreescriben. Si ya existe uno, se detecta y se preserva. |
| Propiedad | Se declara por artifact o modulo, no por directorio completo. |
| Actualizacion o limpieza | Solo se puede actualizar o remover un artifact creado por Pegasus que siga sin cambios del usuario. |
| Artifact existente | No pasa a ser de Pegasus por estar en una ruta conocida. Queda preservado. |

## Inclusion aprobada

El release incluye solamente lo siguiente:

1. Todos los commands, el registro de skills y los assets del registro.
2. Los MCP CBM, Engram y Playwright.
3. El plugin local `engram.ts`, estado de Zellij y plugins de registro. El notifier externo `@mohak34/opencode-notifier@0.2.4` se fija con su `package-lock.json` y se instala solo con `npm ci --ignore-scripts` durante la aceptación aislada.
4. Skills:
   - Todos los Core y SDD.
   - Todos los de contexto, Git y colaboracion, excepto los que comienzan con `sergio-`.
   - De quality, security y operations: solamente `laravel-security` y `lazy-load-prompt-audit`.
   - De domain: solamente `skill-versiones-estandar-asi`.
   - `api-service-contract-documentation`.

`tui.json`, toda configuración/salida de plugins TUI y `judgment-day` no se distribuyen. Si hay una copia local existente, se preserva y no se toca.

Los items no incluidos en esta lista no se distribuyen. No se agregan como efecto indirecto de otro modulo, ni se dejan referencias de configuracion hacia ellos.

## Contrato de MCP y dependencias

Antes de incorporar una dependencia o integracion MCP, Pegasus detecta si ya existe localmente.

| Situacion | Comportamiento obligatorio |
| --- | --- |
| Ya existe la dependencia o integracion | Se ofrece enlazarla. No se reemplaza ni se reinstala. |
| No existe | Se muestra fuente, version fija, integridad y accion a ejecutar. Luego se pide confirmacion del usuario para esa dependencia puntual. |
| Usuario rechaza | No se descarga, instala ni agrega una entrada de configuracion. Tampoco se deja una referencia huerfana. |
| Usuario confirma | Se obtiene e instala un artifact de release fijo, con la procedencia e integridad informadas. |

Cada release de Pegasus registra para cada dependencia su procedencia, version fija e integridad verificable. Nunca se usa `latest`, una version flotante ni una descarga sin identidad de release.

## Herramientas opcionales

Los plugins tienen que ser seguros cuando una herramienta opcional no esta instalada. En particular, el plugin de Zellij queda inerte si Zellij no existe: no falla la instalacion, no agrega una configuracion rota y no intenta instalar Zellij.

## Rollback y limpieza

El rollback solo limpia artifacts que cumplan las dos condiciones: fueron creados por Pegasus y no fueron modificados despues. Si no se puede probar esa propiedad, se preservan.

Un rollback no borra contenido del usuario, incluso cuando comparta una ubicacion con un artifact Pegasus. Los modulos o items que no forman parte de la inclusion aprobada tampoco se agregan ni se eliminan durante esta operacion.

## Control para releases

Antes de publicar, el release tiene que poder demostrar:

- La lista distribuida coincide con la inclusion aprobada.
- Cada artifact declara su propietario y estado esperado para actualizarlo o removerlo.
- Los artifacts existentes del usuario se detectan y preservan.
- Cada MCP o dependencia nueva tiene confirmacion por dependencia, procedencia, version fija e integridad.
- Una negativa del usuario no deja descargas, instalaciones ni referencias de configuracion.
- La ausencia de Zellij mantiene inerte su plugin.
- `tui.json`, configuración/salida TUI, `judgment-day` y todo item no incluido quedan fuera de la distribucion.
- El rollback no elimina contenido del usuario.
