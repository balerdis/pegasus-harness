# Contrato de inclusion de artifacts Pegasus

Este documento fija la decision de distribucion de Pegasus. Pegasus se suma a una instalacion existente del CLI anfitrion — hoy, OpenCode y solamente OpenCode, que es el unico adapter que el release registra (`ADAPTERS`, `src/pegasus/adapters/__init__.py`): no instala ni reemplaza el cliente anfitrion, y no borra, mueve ni sobreescribe un artifact que no haya creado el. Lo que si pisa, y bajo que condicion, esta en la fila "Actualizacion o limpieza" de la tabla de abajo y en [Limitaciones aceptadas](arquitectura/arquitectura.md#limitaciones-aceptadas), que es donde vive el registro.

Toda implementacion y todo release futuro tienen que respetar este contrato. Si una necesidad no entra en estas reglas, se decide antes de distribuirla.

## Modelo aprobado

Pegasus se distribuye de forma aditiva. La instalacion reconoce lo que ya existe y agrega solamente lo que corresponde al release seleccionado.

| Tema | Decision |
| --- | --- |
| Cliente anfitrion | Un CLI soportado ya instalado; hoy el unico soportado es OpenCode. Pegasus no lo instala, actualiza, reemplaza ni desinstala. |
| Artifacts del usuario | Un artifact que el journal no reclama no se borra, mueve ni sobreescribe. Si ya existe uno en una direccion que la instalacion queria ocupar, se detecta, se informa como colision y se preserva: el paso devuelve `SKIP` y nunca escribe (`_file_step`, `src/pegasus/core/planner.py`). |
| Propiedad | Se declara por artifact o modulo y por producto, no por directorio completo. Dos productos instalados bajo el mismo usuario nunca comparten la propiedad de un artifact: cada uno reclama y limpia solo lo suyo. |
| Actualizacion o limpieza | Solo se puede actualizar o remover un artifact que el journal reclama como propio de Pegasus. La huella dejo de ser permiso: dentro de ese conjunto se actualiza y se remueve **sin preguntar si el usuario lo edito despues**. `install` reescribe toda direccion reclamada cuyo contenido difiera del que se quiere colocar, y `uninstall` borra toda direccion reclamada, en los dos casos sin mirar de quien es el contenido actual (`_file_step` y `retire`, `src/pegasus/core/planner.py`). Lo que protege una edicion a mano es el snapshot previo a escribir, no una negativa a escribir — ver [Limitaciones aceptadas](arquitectura/arquitectura.md#limitaciones-aceptadas). |
| Artifact existente | No pasa a ser de Pegasus por estar en una ruta conocida. Queda preservado. |

## Inclusion aprobada

Esta lista describe el release de Pegasus en si mismo: el binario `pegasus` que este repositorio
construye y publica, con la identidad y el contenido que trae de fabrica. No describe ningun otro
binario basado en el mismo motor — una distribucion que construye su propio `identity.json` y su
propio contenido con `tools/build_zipapp.py` decide su propia lista de inclusion, y esta seccion no
se le aplica.

El release incluye solamente lo siguiente:

1. Todos los commands, el registro de skills y los assets del registro.
2. Los cinco servidores MCP que el contenido embarca (`src/pegasus/content/mcp/`), cada uno con su forma de distribucion declarada en el descriptor: `cbm` y `engram` (`download`: binario de release con version y `sha256` fijos), `playwright` (`npm`: tarball del registry con `integrity` y su propio `package-lock.json`), y `context7` y `jira` (`remote`: un endpoint HTTPS, sin nada que descargar ni materializar). Ninguno se instala si no se lo nombra con `--mcp`.
3. Los seis plugins locales aprobados (`src/pegasus/adapters/opencode/assets/plugins/`). Cuatro se instalan con el prefijo del binario — `pegasus` en esta distribución — y dos conservan su nombre de origen:
   - `engram.ts`, sin prefijo.
   - `zellij-status.js`, sin prefijo.
   - `zellij-state.ts` → `pegasus-zellij-state.ts`, el estado de Zellij.
   - `skill-registry.ts` → `pegasus-skill-registry.ts`, el plugin de registro (acompañado de `pegasus-skill-registry.env`).
   - `apply-patch-scope.ts` → `pegasus-apply-patch-scope.ts`, que agrega un párrafo a la descripción de `apply_patch` para que su imperativo de apertura no se lea como una prohibición del resto de las herramientas.
   - `orchestrator-notifier.ts` → `pegasus-orchestrator-notifier.ts`, que avisa por `notify-send` cuando la sesión del orquestador queda `idle` o bloqueada esperando un permiso.

   El notifier externo `@mohak34/opencode-notifier@0.2.4` se fija con su `package-lock.json` y se instala solo con `npm ci --ignore-scripts` durante la aceptación aislada.
4. Skills:
   - Todos los Core y SDD.
   - Todos los de contexto, Git y colaboracion, excepto los que comienzan con `sergio-`.
   - De quality, security y operations: solamente `lazy-load-prompt-audit`.
   - De domain: ninguna. `skill-versiones-estandar-asi` y `laravel-security` se retiraron del contenido embarcado: el primero codifica el estándar de tecnología interno de una organización y el segundo llegó por la misma mudanza, y ninguno de los dos es guía genérica que corresponda que embarque un producto público.
   - `api-service-contract-documentation`.

`tui.json`, toda configuración/salida de plugins TUI, `judgment-day` y la referencia de transporte de deployment de `lazy-load-prompt-audit` no se distribuyen. La ausencia de esa referencia bloquea el flujo de deployment con `blocked-missing-reference`; no se infiere ni se recrea. Si hay una copia local existente, se preserva y no se toca.

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

El rollback limpia los artifacts que el journal reclama como creados por Pegasus, hayan sido modificados despues o no. La condicion es una sola —que el journal los reclame—, y no se puede probar esa propiedad sobre una direccion que no figura ahi: esa se preserva sin tocarla.

Un rollback no borra contenido del usuario que viva en una direccion que Pegasus no posee, incluso cuando comparta un archivo con un artifact Pegasus: dentro de un archivo de configuracion Pegasus posee claves, nunca el archivo, asi que el resto del documento sobrevive y un archivo que tuvo que crear puede quedar vacio. Un item agregado a una lista es la unica excepcion en el otro sentido: se lo localiza por huella, asi que uno que el usuario edito hasta volverlo irreconocible no se encuentra, se informa como `unaccounted` y se queda donde esta (`_retire_key`, `src/pegasus/core/planner.py`). Los modulos o items que no forman parte de la inclusion aprobada tampoco se agregan ni se eliminan durante esta operacion.

## Limitaciones conocidas

Este documento ya no las repite: viven en un solo lugar, junto con su motivo. Una edicion a mano sobre un artifact de Pegasus no sobrevive al proximo `install` y `uninstall` la borra, los `append` quedan fuera del aviso `overwritten` por construccion y `uninstall` no tiene aviso equivalente — el porque de cada una y la recuperacion por snapshot, con su ventana de cinco generaciones, estan en [Limitaciones aceptadas](arquitectura/arquitectura.md#limitaciones-aceptadas). De las listas de "Inclusion aprobada", los servidores MCP y los plugins de OpenCode ya no se mantienen a mano sin control: `tests/test_inclusion_contract.py` deriva del arbol los servidores en `src/pegasus/content/mcp/*.md` y los plugins en `src/pegasus/adapters/opencode/assets/plugins/`, los compara contra los nombres que esta seccion declara en las dos direcciones, y ademas verifica que a quien esta seccion describe "sin prefijo" o "con prefijo" coincida con `_RENAMED_ASSETS` (`src/pegasus/adapters/opencode/adapter.py`). Lo que sigue sin verificacion automatica es la lista de skills — su enumeracion por categoria en esta seccion no se deriva del contenido embarcado — y que la salida realmente distribuida en un release coincida con lo que el arbol fuente contiene; eso sigue figurando en [Deudas sin unidad asignada](arquitectura/arquitectura.md#deudas-sin-unidad-asignada) con lo que hay que hacer en cada release hasta que exista.

## Control para releases

Antes de publicar, el release tiene que poder demostrar:

- La lista distribuida coincide con la inclusion aprobada.
- Cada artifact declara su propietario. La propiedad, y solo ella, habilita actualizarlo o removerlo.
- Los artifacts existentes del usuario se detectan y preservan.
- Cada MCP o dependencia nueva tiene confirmacion por dependencia, procedencia, version fija e integridad.
- Una negativa del usuario no deja descargas, instalaciones ni referencias de configuracion.
- La ausencia de Zellij mantiene inerte su plugin.
- `tui.json`, configuración/salida TUI, `judgment-day`, la referencia de transporte de deployment y todo item no incluido quedan fuera de la distribucion.
- El rollback no elimina contenido que Pegasus no posea.

De estos puntos, `tests/test_inclusion_contract.py` prueba que los servidores MCP y los plugins de OpenCode nombrados en la inclusion aprobada coincidan, en las dos direcciones, con lo que el arbol fuente contiene, y que el prefijo declarado para cada plugin coincida con `_RENAMED_ASSETS`. Sigue demostrandose a mano, sin una prueba que lo derive, que la lista efectivamente distribuida en un release (el binario `pegasus` publicado) coincida con la inclusion aprobada — esa comparacion incluye ademas las skills, que el test no cubre. Eso esta anotado como deuda en [Deudas sin unidad asignada](arquitectura/arquitectura.md#deudas-sin-unidad-asignada).
