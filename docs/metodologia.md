# Arquitectura operativa de Pegasus Harness

Pegasus no es un framework que reemplace el criterio del equipo. Es una capa de trabajo para OpenCode: ordena cómo se entiende un cambio, dónde queda su evidencia y quién tiene la responsabilidad de cada paso.

## El recorrido normal

1. El orquestador confirma contexto, modo de ejecución, persistencia, estrategia de entrega y presupuesto de revisión.
2. SDD deja claro qué se quiere cambiar y cómo se va a probar.
3. El agente de apply implementa solamente las tareas asignadas.
4. `sdd-verify`, en un contexto fresco, contrasta requisitos, diseño, tareas y evidencia real de ejecución.
5. Si el cambio ya está probado, se archiva. Si no, vuelve al punto que tenga el problema.

No hay atajo útil acá: CBM ayuda a leer el código; los tests y los checks de runtime prueban comportamiento.

## Las piezas y para qué sirven

| Pieza | Para qué se usa | Qué no hace |
| --- | --- | --- |
| SDD | Lleva un cambio desde exploración hasta verificación: propuesta, spec, diseño, tareas, apply, verify y archive. | No reemplaza el criterio técnico ni aprueba un cambio sin evidencia. |
| TDD | Cuando el proyecto lo habilita, pide escribir primero la prueba que falla, luego implementar y recién después refactorizar. | No se activa por nombre: depende del modo Strict TDD y de que exista un runner. |
| OpenSpec | Guarda proposal, specs, design y tasks como archivos versionables bajo `openspec/`. | No obliga a usar Engram ni crea evidencia de runtime por sí solo. |
| Engram | Conserva memoria de proyecto, decisiones, progreso y resúmenes entre sesiones. | No sustituye el código actual, Git ni una prueba recién ejecutada. |
| ChainPR | Mantiene una revisión manejable cuando el cambio supera el presupuesto. Divide por unidades autónomas, con tests y rollback en la misma unidad. | No permite mezclar estrategias ni esconder un diff grande sin una excepción explícita. |
| CBM | Da inteligencia de código: estructura, callers, flujos e impacto. | No es una prueba de aceptación ni un test de comportamiento. |

## SDD en la práctica

La unidad de trabajo es un cambio con artefactos y evidencia, no una conversación suelta.

```text
explore → proposal → spec → design → tasks → apply → verify → archive
```

- **Explore**: mira el sistema antes de comprometer una solución.
- **Proposal**: fija intención, alcance, riesgos y lo que queda afuera.
- **Spec**: define requisitos y escenarios verificables.
- **Design**: baja decisiones técnicas, flujos y estrategia de pruebas.
- **Tasks**: corta el trabajo en unidades implementables y revisables.
- **Apply**: escribe el cambio siguiendo spec y diseño.
- **Verify**: prueba en forma independiente que el cambio cumple lo pedido.
- **Archive**: deja el cambio cerrado y sincroniza la especificación cuando corresponde.

Antes de iniciar una fase SDD, el orquestador necesita el pre-chequeo de sesión: modo interactivo o automático, backend de persistencia, estrategia de PR y presupuesto de revisión. Si falta eso, pregunta y frena; no lo inventa.

## TDD: cuándo aplica

`sdd-init` detecta el runner y guarda la capacidad de testing. Si Strict TDD está activo y hay runner, apply trabaja con esta secuencia por tarea:

```text
RED: prueba escrita y fallando → GREEN: implementación que pasa → REFACTOR: limpieza con la prueba en verde
```

La evidencia de ese ciclo queda registrada. Si Strict TDD no está activo, igual hay evidencia mínima por unidad: test enfocado, escenario de runtime cuando exista una frontera real, y límite de rollback. Ninguna de las dos modalidades autoriza marcar una tarea completa con checks fallando.

## OpenSpec y Engram: dónde queda el contexto

El equipo elige el backend al inicio de la sesión; no hay uno obligatorio para todos los proyectos.

| Modo | Fuente de trabajo | Persistencia |
| --- | --- | --- |
| `openspec` | Archivos del repo | `openspec/changes/<change>/` |
| `engram` | Memoria de proyecto | tópicos `sdd/<change>/<artifact>` |
| `hybrid` | Ambos | archivos y memoria, reconciliados |
| `none` | Conversación y estado actual | no crea artefactos SDD |

OpenSpec es cómodo para revisar en Git. Engram sirve para recuperar una decisión o un handoff entre sesiones. En los dos casos, la evidencia actual gana: un test de hoy y el código actual valen más que un progreso viejo.

## ChainPR: proteger la revisión

Si el forecast supera unas 400 líneas cambiadas, tiene riesgo alto o recomienda PRs encadenados, la decisión se toma antes de apply. Cada PR tiene una sola unidad de entrega, sus pruebas, su rollback y un límite claro.

| Situación | Camino |
| --- | --- |
| Cambio enfocado dentro del presupuesto | Un solo PR. |
| Unidades independientes que pueden llegar a `main` por separado | Stacked PRs hacia `main`. |
| La funcionalidad necesita integrarse primero como conjunto | Feature branch chain con un tracker draft; cada hijo apunta al PR anterior, no a `main`. |
| Diff generado o migración que no se puede separar | Excepción `size:exception` aceptada explícitamente por quien mantiene el repo. |

No se cambia de estrategia a mitad de la cadena. Si el diff trae cambios que no pertenecen a la unidad actual, se retargetea o se rebasea hasta dejar la revisión limpia.

## Roles y límites

| Rol | Responsabilidad | Límite importante |
| --- | --- | --- |
| Persona responsable | Elige alcance, proveedor/modelo, dependencias opcionales y estrategia de entrega. | No delega su decisión de producto ni el manejo de credenciales. |
| `pegasus-orchestrator` | Ordena fases, valida gates y delega el trabajo correcto. | No ejecuta inline las fases que pertenecen a un subagente. |
| Agente SDD de planificación | Produce explore, proposal, spec, design o tasks según la fase. | No implementa ni declara listo un cambio por su cuenta. |
| `sdd-apply` | Implementa las tareas asignadas y deja evidencia de unidad de trabajo. | No ejecuta verify final ni toma tareas fuera de su asignación. |
| `sdd-verify` | Es la única autoridad de readiness para cambios ejecutables o de configuración. | No arregla lo que encuentra; informa el problema para remediación. |
| CBM | Mapea la superficie de código antes de tocar símbolos compartidos. | No reemplaza tests ni runtime checks. |

## Dónde mirar en el repo

- [README.md](../README.md): adopción, límites y pre-chequeos.
- [MANUAL.md](../MANUAL.md): instalación y uso de OpenCode con Pegasus.
- [src/pegasus/content/agents/pegasus-orchestrator.md](../src/pegasus/content/agents/pegasus-orchestrator.md): responsabilidad del orquestador.
- [contrato-inclusion-artifacts.md](contrato-inclusion-artifacts.md): qué puede entrar al payload y qué queda afuera.

El resultado buscado es simple: cada cambio puede explicar qué se hizo, por qué, cómo se probó y qué se puede revertir sin tocar trabajo ajeno.
