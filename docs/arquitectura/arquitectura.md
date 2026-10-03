# Pegasus Harness: núcleo agnóstico y adapters por CLI

Pegasus separa **qué distribuye** (contenido común a cualquier CLI de agentes) de **cómo lo materializa** (un adapter por CLI). El motor deja de conocer nombres de CLIs: recibe contenido del núcleo, se lo da al adapter, y el adapter decide dónde va y con qué forma. Fue un rediseño con ruptura de compatibilidad respecto de v3.1.x, entregado como v4 y continuado desde entonces.

Este documento se escribió para ese rediseño y siguió creciendo con el producto. El corte numerado de unidades es el plan de v4 y su ejecución, y está cerrado; lo que se agregó después vive en su propia sección, y no lleva número porque no salió de un plan sino de instalaciones reales. Al 5.8.0 lo que sigue acá es la arquitectura vigente, no un registro histórico — cuando una parte deja de serlo, se corrige o se anota como deuda, nunca se deja parada.

Este documento fija la arquitectura antes de escribir código. No es un plan de tareas.

---

## Decisiones tomadas

| Tema | Decisión |
|------|----------|
| Estilo arquitectónico | Hexagonal (puertos y adaptadores). No Clean Architecture. |
| Versión | `4.0.0`, breaking change explícito. |
| CLIs soportados en 4.0.0 | Solo OpenCode. La arquitectura admite N sin tocar el núcleo. |
| Migración desde v3.1.x | No hay. El usuario desinstala v3 e instala v4. |
| Catálogo de artefactos | Generado, no escrito a mano. |
| Agentes SDD | Se cablean los 10 de la línea SDD (hoy hay 1 solo). |
| Interfaz de usuario | TUI por defecto + flags equivalentes para modo desatendido. |
| Lenguaje y dependencias | Python 3.12+, sin ninguna dependencia. El frontmatter de los descriptores se parsea con un lector propio y estricto, que rechaza lo que no entiende en vez de interpretarlo a medias. |
| Punto de entrada | Un solo archivo ejecutable (`zipapp` con shebang y bit ejecutable), instalado en `~/.local/bin/pegasus`. Sin venv privado. |

### Las dos reglas que gobiernan el diseño

> **1. Ningún módulo fuera de `adapters/` puede mencionar el nombre de un CLI.**

Si aparece un `if cli_id == "opencode"` en `core/`, `tui/` o `infra/`, es un defecto de arquitectura, no un detalle de implementación. Un test lo verifica automáticamente.

> **2. El núcleo guarda la intención; el adapter guarda el deletreo.**

El núcleo declara *qué se quiere que pase*. El adapter sabe *cómo se escribe eso en un CLI concreto*. Un campo que sirve para un solo CLI no pertenece al descriptor, aunque el contenido haya llegado con ese campo desde una versión anterior.

La prueba para saber de qué lado va un campo: **¿tendría sentido en un CLI que todavía no soportamos?** Si la respuesta es no, es deletreo y va al adapter.

---

## Qué problema resuelve

En v3.1.2 la adaptación a un CLI no vive en ningún lugar identificable. Está repartida en tres sitios:

| Dónde | Qué hay hoy | Consecuencia |
|-------|-------------|--------------|
| `manifests/artifact-catalog.json` | Cada artefacto declara `client: opencode` y un `target` con la ruta literal de OpenCode | El contenido y su ubicación están fusionados |
| `bin/pegasus:390` | `Path(target["opencode_root" if entry["client"] == "opencode" else "claude_root"])` | Solo existen dos raíces posibles, cableadas |
| `source/opencode/opencode.json` | 5 artefactos `json-key` con el esquema exacto de OpenCode | Agregar un CLI con otro formato de config requiere tocar el motor |

Agregar Codex hoy significa modificar el motor, el catálogo y el validador. En v4 significa escribir un directorio nuevo bajo `adapters/` y registrarlo.

---

## Arquitectura

```
        PUERTOS DRIVER                                     PUERTOS DRIVEN
        (quién nos usa)                                    (a quién usamos)

   ┌──────────────┐                                    ┌──────────────────┐
   │     TUI      │──┐                            ┌───►│   CliAdapter     │
   └──────────────┘  │                            │    │  opencode        │
   ┌──────────────┐  │   ┌────────────────────┐   │    │  (claude, codex) │
   │  CLI (flags) │──┼──►│      NÚCLEO        │───┤    └──────────────────┘
   └──────────────┘  │   │                    │   │    ┌──────────────────┐
   ┌──────────────┐  │   │  contenido         │   ├───►│   FileSystem     │
   │ Agente (JSON)│──┘   │  planner           │   │    │  posix / windows │
   └──────────────┘      │  journal           │   │    └──────────────────┘
                         │  registry          │   │    ┌──────────────────┐
                         └────────────────────┘   ├───►│  JournalStore    │
                                                  │    └──────────────────┘
                                                  │    ┌──────────────────┐
                                                  └───►│ DependencyFetcher│
                                                       │  (MCPs)          │
                                                       └──────────────────┘
```

El núcleo no importa nada de `adapters/` ni de `infra/`. Recibe implementaciones por constructor.

---

## El núcleo de contenido

Todo el contenido tiene una sola forma: **un archivo markdown con frontmatter**. El frontmatter es el descriptor, y lo que sigue es el cuerpo. Un único formato para todas las categorías, y por lo tanto un único parser.

| Categoría | Contiene | Qué es agnóstico |
|-----------|----------|------------------|
| `skills/` | `SKILL.md` + `references/` | Todo |
| `agents/` | Rol, modo, herramientas, delegación permitida, y el prompt como cuerpo | Todo el cuerpo; el formato de declaración no |
| `commands/` | Descripción, rol que lo ejecuta, contexto de ejecución | Todo el cuerpo; el frontmatter no |
| `system-prompt/` | La instrucción global que el CLI carga en cada sesión | Todo el cuerpo; el nombre y la ubicación del archivo no |
| `mcp/` | Servidores MCP: id, versión fija, integridad, argv de instalación y runtime, probe | Todo |
| `policies/` | TDD estricto, ChainPR, gates de fase, backend de artefactos | Todo |

`system-prompt/` es una categoría propia y no una política: es un artefacto único con su propio render. OpenCode lo instala como `AGENTS.md` en la raíz de su configuración; otro CLI puede darle otro nombre, otra ubicación, o cargarlo desde su archivo de settings.

**No hay una categoría `prompts/`.** El prompt de un agente es el cuerpo del archivo del agente. Que ese prompt viaje después en un archivo separado o embebido en la declaración del agente es una decisión del CLI, no del contenido, y por eso existe la capacidad `prompts`: OpenCode la declara y recibe dos artefactos, un CLI que embebe el prompt la niega y recibe uno solo.

### Ejemplo de descriptor

```markdown
---
name: sdd-verify
description: Sole readiness authority for executable and configuration changes
mode: subagent
requires_tools: [read, write, bash]
optional_tools: [codebase-memory]
model_configurable: true
---

# SDD Verify

You are Pegasus's sole readiness authority for executable and configuration changes.
...
```

Ese descriptor no dice nada sobre OpenCode. El adapter de OpenCode lo convierte en una entrada bajo `agent` de `opencode.json` más un archivo de prompt; un adapter de Claude Code lo convertiría en un `.claude/agents/sdd-verify.md` con frontmatter y el prompt embebido. Ninguno de los dos requiere tocar el descriptor.

### Estado del contenido

| Categoría | Presente | Pendiente |
|-----------|---------:|-----------|
| `skills/` | 26, más `_shared/` | Nada |
| `commands/` | 16 | Nada |
| `agents/` | 12 | Nada |
| `system-prompt/` | 1 | Nada |
| `mcp/` | 5 | Nada |

### Qué salió del frontmatter heredado

El frontmatter que llegó desde v3 mezclaba conceptos agnósticos con deletreos de OpenCode. Cada uno se reemplazó por la intención que expresaba:

| Campo heredado | Qué era en realidad | Campo agnóstico |
|----------------|---------------------|-----------------|
| `subtask: true` | Contexto de ejecución | `execution: isolated \| inline` |
| `agent: pegasus-orchestrator` | Agente propio de Pegasus | `runs_as: orchestrator` |
| `agent: plan` / `agent: build` | Agentes nativos de OpenCode | `runs_as: planner \| builder` |
| `agent:` ausente | El agente por defecto del CLI | `runs_as: default` |
| `permission.task` | A qué agentes puede delegar | `may_delegate_to: [...]` |

El adapter de OpenCode mapea `orchestrator` a `pegasus-orchestrator`, `planner` a su agente nativo `plan`, `isolated` a `subtask: true`, y `may_delegate_to` a su bloque `permission`. Otro CLI usa sus propios nombres sin que el descriptor cambie.

### Duplicación heredada, ya resuelta

v3 embarcaba 92 artefactos con solo 78 digests únicos. Nueve skills de la línea SDD viajaban dos veces, byte a byte idénticas, bajo `skills/` y bajo `prompts/sdd/`. Como `opencode.json` declara `"skills": {"paths": ["./skills"]}`, las copias bajo `prompts/` nunca se cargaban: eran payload muerto en toda instalación de v3.1.1. El único archivo de `prompts/` que se usaba era `sdd-verify.md`, referenciado explícitamente como prompt de agente, y hoy es el cuerpo de `agents/sdd-verify.md`.

### El pipeline de materialización

```
1. RESOLVE      el núcleo arma el conjunto de contenido a instalar
2. ADAPT        el adapter mapea categoría → ruta concreta de ese CLI
3. DECORATE     el adapter envuelve: frontmatter, claves JSON, formato de config
4. MATERIALIZE  el motor escribe, con journal de ownership y rollback
```

Los pasos 1 y 4 son núcleo puro y no conocen ningún CLI. Los pasos 2 y 3 son exclusivos del adapter. El motor nunca inspecciona el contenido de lo que escribe.

---

## Puertos

### `CliAdapter` — el puerto principal

Separa **dónde** (rutas) de **cómo** (render). Esa separación es la que evita que el motor tenga que preguntar de qué CLI se trata.

```python
class CliAdapter(Protocol):
    # --- Identidad ---
    @property
    def id(self) -> str: ...
    @property
    def display_name(self) -> str: ...
    def tier(self) -> SupportTier: ...          # FULL | PARTIAL | EXPERIMENTAL
    def capabilities(self) -> CapabilityManifest: ...

    # --- Detección ---
    def detect(self, env: Environment) -> Detection: ...

    # --- Dónde: layout de rutas ---
    def layout(self, env: Environment) -> Layout: ...

    # --- Cómo: render de cada categoría. Cada uno recibe el layout ya
    # resuelto, así el adapter no guarda estado propio de una máquina. ---
    def render_skill(self, layout: Layout, skill: Skill) -> list[Artifact]: ...
    def render_agent(self, layout: Layout, agent: AgentDescriptor) -> list[Artifact]: ...
    def render_command(self, layout: Layout, command: CommandDescriptor) -> list[Artifact]: ...
    def render_prompt(self, layout: Layout, prompt: PromptDescriptor) -> list[Artifact]: ...
    def render_mcp(self, layout: Layout, server: McpServer, resolved: Resolved) -> list[Artifact]: ...
    def render_policy(self, layout: Layout, policy: PolicyDescriptor) -> list[Artifact]: ...

    # --- Lo que el adapter aporta por su cuenta ---
    def own_artifacts(self, layout: Layout) -> list[Artifact]: ...

    # --- Modelos: solo si capabilities().per_agent_model es True ---
    def model_catalog(self, env: Environment) -> ModelCatalog: ...
    def read_model_assignments(self, env: Environment) -> dict[str, ModelAssignment]: ...
```

### `Layout` — las anclas de ruta

```python
@dataclass(frozen=True)
class Layout:
    config_dir: Path            # raíz de configuración del CLI
    settings_file: Path | None  # archivo de config principal, si existe
    skills_dir: Path | None
    agents_dir: Path | None
    commands_dir: Path | None
    prompts_dir: Path | None  # None si el CLI embebe el prompt en el agente
    plugins_dir: Path | None
    system_prompt_file: Path | None
```

Un `None` significa "este CLI no tiene ese concepto" y debe ser coherente con el manifiesto de capacidades. El registry lo verifica al registrar.

### `Artifact` — la unidad que el motor sabe escribir

El motor conoce exactamente dos formas de artefacto. Nada más. El adapter las entrega ya terminadas: el motor nunca abre `content` ni interpreta `value`.

```python
@dataclass(frozen=True)
class FileArtifact:
    id: str
    path: Path                  # ruta absoluta, ya resuelta por el adapter
    content: bytes              # contenido final, ya decorado
    mode: int = 0o644

@dataclass(frozen=True)
class ConfigKeyArtifact:
    id: str
    path: Path                  # archivo de configuración
    pointer: str                # dirección RFC 6901, ej. "/agent/sdd-apply/model"
    value: object
    codec: Codec = Codec.JSON   # cómo se parsea y serializa ese archivo

Artifact = FileArtifact | ConfigKeyArtifact
```

Direccionar por puntero en lugar de por clave plana es lo que permite escribir `/agent/sdd-apply/model` sin que el motor entienda el esquema del CLI. En v3 solo se podía escribir en la raíz del documento, y por eso configurar un modelo obligaba a reescribir el bloque de agentes completo.

#### Las cuatro operaciones del motor

Es todo lo que el motor sabe hacer con un artefacto. Cada operación tiene exactamente dos implementaciones, y agregar un CLI no agrega ninguna.

| Operación | `FileArtifact` | `ConfigKeyArtifact` |
|-----------|----------------|---------------------|
| Detectar colisión | ¿El path ya existe? | ¿El puntero ya resuelve a algo? |
| Escribir | Escritura atómica de `content` | `set_at(doc, pointer, value)` y reescritura atómica |
| Hashear | `sha256(content)` | `sha256` de la serialización canónica de `value` |
| Revertir | Borrar el archivo | `unset_at(doc, pointer)` |

`set_at` y `unset_at` son dos funciones genéricas que navegan un árbol de diccionarios y listas creando lo que falte. No mencionan ningún CLI.

#### La excepción: punteros que agregan a una lista

Un puntero terminado en `/-` no direcciona un casillero sino el final de una lista. Hoy tres artefactos lo usan: `/instructions/-`, `/plugin/-` y `/skills/paths/-`. Eso rompe dos de las cuatro operaciones, y las dos se arreglan con la huella:

| Operación | Por qué no sirve lo normal | Cómo se resuelve |
|-----------|---------------------------|------------------|
| Detectar colisión | En `/-` nunca resuelve nada, así que jamás habría colisión y reinstalar duplicaría la entrada | Hay colisión si algún ítem de la lista tiene la huella del valor que íbamos a agregar |
| Revertir | Guardar el índice no sirve: el usuario puede reordenar la lista y el índice pasaría a apuntar a algo suyo | Se busca el ítem cuya huella coincide con `after_digest` y se quita ese |

Por eso el ítem se identifica por **lo que es** y no por **dónde está**.

Eso tiene una consecuencia que hay que decir en voz alta: **un ítem de lista no tiene dirección propia que inspeccionar, y esa falta de dirección es la que le impide a un append comportarse como el resto del desinstalador.** Si la lista todavía tiene ítems y ninguno lleva la huella registrada, hay dos causas posibles y son indistinguibles:

- el usuario borró nuestro ítem, o
- el usuario lo editó en el lugar, y ahora es idéntico a un ítem que hubiera puesto él.

No hay dato en el journal que las separe. Ninguna de las dos es una remoción, así que el desinstalador las reporta como un segundo resultado: **`unaccounted`**. `removed` es una afirmación sobre algo que Pegasus hizo, y acá no sería cierta.

**La ambigüedad necesita sobrevivientes**, y afirmarla donde no existe sería su propia imprecisión. Los cuatro estados posibles:

| Estado al desinstalar | ¿Ambiguo? | Resultado |
|-----------------------|-----------|-----------|
| El archivo de configuración no existe | No: se fue con el archivo | `removed` |
| El archivo existe pero la lista no | No: se fue con la lista | `removed` |
| La lista existe y está vacía | No: no queda nada que pueda ser una versión cambiada del nuestro | `removed` |
| La lista tiene ítems y ninguno es el nuestro | **Sí** | `unaccounted` |

Además, dos artefactos no pueden agregar **el mismo valor** al mismo puntero: la lista no podría distinguirlos y nada aguas abajo podría decir cuál de los dos tiene. Agregar valores distintos sí es legítimo y por eso los appends quedan exentos de la regla general de direcciones únicas.

#### Códecs de configuración

El puntero navega cualquier árbol, pero parsear y serializar el archivo depende de su formato. El adapter lo declara y el motor delega:

```python
class Codec(Enum):
    JSON = "json"
    TOML = "toml"
    YAML = "yaml"
```

En 4.0.0 todos los artefactos son JSON. El campo existe igual porque agregarlo después sería un cambio incompatible del contrato `pegasus/artifact-catalog/v4`, y el primer CLI con configuración en TOML o YAML lo va a necesitar.

Cada códec debe garantizar dos cosas: **serialización canónica** (mismo valor, mismos bytes, para que las huellas sean estables) y **preservación de lo ajeno** (las claves que Pegasus no escribió sobreviven intactas al ciclo de lectura y escritura).

#### Casos que parecen no entrar, y entran

| Caso | Forma |
|------|-------|
| Plugin `.ts`, prompt `.md`, skill con referencias | Uno o varios `FileArtifact` |
| Binario ejecutable | `FileArtifact` con `mode=0o755` |
| Agregar un ítem a un array de configuración | `ConfigKeyArtifact` con puntero terminado en `/-` |
| Servidor MCP | `ConfigKeyArtifact` con puntero `/mcp/<id>` |
| Un solo campo dentro de una definición existente | `ConfigKeyArtifact` con puntero al campo |

Regla de higiene: si aparece un caso que no entra en ninguna de las dos formas, es señal de que el adapter está intentando delegar lógica propia al motor. La solución es resolverlo en el adapter, no agregar una tercera forma.

### Artefactos propios del adapter

Casi todo lo que un adapter escribe viene del núcleo: recibe un descriptor y lo materializa. Pero hay archivos que existen **solo porque un CLI funciona como funciona**, y para esos no hay descriptor posible.

En OpenCode son doce: seis plugins escritos contra su API de plugins, el `package.json` y el lockfile de los que esos plugins dependen, la herramienta que uno de ellos invoca con su launcher, su plantilla de entorno, y un archivo de datos del propio adapter.

```python
def own_artifacts(self, environment: Environment) -> list[Artifact]: ...
```

Que un adapter tenga recursos propios de su tecnología es normal en puertos y adaptadores: un driver de base de datos lleva su gramática SQL, un adapter REST lleva sus serializadores, y el dominio no conoce ninguno de los dos. La invariante de la arquitectura es la **dirección de la dependencia** — el adapter conoce al núcleo, el núcleo no conoce al adapter — y no que todo lo que el adapter produce tenga que originarse en el núcleo.

El detalle que mantiene la flecha en su lugar: `own_artifacts` devuelve `Artifact`, un tipo del núcleo. El adapter aporta cosas propias, pero las entrega hablando el vocabulario que define el puerto, y el motor las materializa sin saber que son TypeScript ni que existe OpenCode.

**Es una puerta de escape, y las puertas de escape se abusan.** Dos candados la protegen:

| Candado | Qué impide |
|---------|------------|
| Contención, verificada por el registry | Que un adapter escriba fuera del `config_dir` de su propio CLI |
| La regla 2 como criterio de admisión | Que entre acá algo que podría tener forma agnóstica, vaciando el núcleo de a poco |

Si un archivo tendría sentido en un CLI que todavía no soportamos, va al núcleo. Usar `own_artifacts` para evitar escribir un descriptor es exactamente cómo se degrada esta arquitectura.

### Puertos secundarios

| Puerto | Responsabilidad | Por qué está separado |
|--------|-----------------|-----------------------|
| `FileSystem` | Escritura atómica, permisos, rutas de usuario, espacio | Windows y POSIX difieren; además hace testeable el motor sin tocar disco |
| `JournalStore` | Persistir y leer el journal de ownership | Permite tests con journal en memoria |
| `DependencyFetcher` | Materializar, verificar y probar MCPs | Aísla la red y la deja ocurrir solo en instalación; el contrato se diseña de cero en la unidad 8, no se hereda de v3 |
| `ModelCatalog` | Proveedores y modelos disponibles | Es parte del adapter, no un puerto global: cada CLI resuelve modelos a su manera |

---

## Manifiesto de capacidades: falla cerrado

Cada adapter declara qué soporta. El registry **rechaza registrar** un adapter cuyo manifiesto no coincida con lo que realmente implementa. Un adapter mal escrito no arranca el programa; no falla a mitad de una instalación.

```python
@dataclass(frozen=True)
class CapabilityManifest:
    cli_id: str
    skills: bool = False
    system_prompt: bool = False
    slash_commands: bool = False
    sub_agents: bool = False
    prompts: bool = False          # el prompt del agente va en un archivo aparte
    mcp: bool = False
    per_agent_model: bool = False
    schema: str = "pegasus/capability-manifest/v1"
```

Validaciones al registrar:

- [ ] `manifest.cli_id == adapter.id`
- [ ] Cada capacidad en `True` que se materializa como archivo tiene su ancla de `Layout` no nula
- [ ] Cada capacidad en `True` tiene su método `render_*` implementado
- [ ] Cada capacidad en `False` no expone ruta ni render (evita capacidades fantasma)
- [ ] `per_agent_model` en `True` implica los tres métodos de modelos
- [ ] No hay dos adapters con el mismo `id`

Este es el mecanismo que evita que la abstracción se degrade cuando se agregue el cuarto o quinto CLI.

**El ancla obligatoria solo aplica a capacidades basadas en archivos.** Los subagentes, los servidores MCP y la asignación de modelo pueden vivir dentro del archivo de configuración en un CLI y como archivos en otro. Exigirle un directorio a los dos obligaría a uno a declarar una ruta que nunca usa, que es la misma ficción que el chequeo de capacidades fantasma intenta evitar. Para esas capacidades la prueba de soporte es el render, no la ruta.

**Las capacidades sin ancla dedicada se validan solo por su render.** `mcp` y `per_agent_model` escriben adentro del archivo de configuración compartido, que también guarda claves de otras capacidades y del propio usuario. Que ese archivo exista no prueba que ninguna capacidad en particular esté soportada, así que exigirlo como ancla rechazaría adapters correctos: un CLI con archivo de settings pero sin soporte MCP sería acusado de exponer una capacidad fantasma.

**Los plugins no son una capacidad.** No hay categoría de contenido para ellos y no puede haberla: un plugin de OpenCode es TypeScript escrito contra su propia API, y no existe una forma agnóstica que sirva también para los hooks de Claude Code. Viajan por `own_artifacts`, y el manifiesto queda siendo lo que debe ser: un contrato sobre cómo sale el contenido del núcleo.

**El layout se prueba contra un home inexistente.** Construir un `Layout` tiene que ser aritmética de rutas pura. Si un adapter consultara el disco, el resultado del registro dependería del estado de la máquina: pasaría en la del desarrollador, donde el directorio del CLI ya existe, y fallaría en la de un usuario que instaló el CLI pero nunca lo abrió. El registry lo prueba contra un home que no existe, así que ese error se cae en el primer test.

---

## Detección de CLIs

Chequeo puro de sistema de archivos y PATH. **Sin ejecutar el CLI.** Ejecutar binarios de terceros para detectarlos es lento, falla en entornos restringidos y no es portable a Windows.

```python
@dataclass(frozen=True)
class Detection:
    installed: bool        # binario encontrado en PATH
    binary_path: Path | None
    config_dir: Path | None
    config_found: bool     # el directorio de config existe
```

Un CLI se considera presente si `installed or config_found`. Los dos casos importan: alguien puede tener config sin el binario en PATH (instalación en ubicación no estándar), o el binario sin haberlo corrido nunca.

El menú de instalación lista **solo CLIs soportados**. Un CLI instalado pero sin adapter no aparece.

---

## Journal de ownership v4

El journal es lo que hace a Pegasus aditivo: registra qué creó, para poder retirarse sin llevarse trabajo ajeno.

### Qué cambia respecto de v3

| v3 | v4 | Por qué |
|----|----|---------|
| `baseline_digest`, usada como permiso para escribir | `after_digest`, que identifica qué es nuestro pero ya no decide si se pisa | Instalar y desinstalar escriben todo lo que el journal reclama sin mirar la huella; volver atrás es trabajo del snapshot, no del journal |
| Una instalación global | Instalaciones por CLI | Se puede tener Pegasus en dos CLIs con ciclos de vida independientes |
| Clave plana (`key`) | JSON Pointer | El motor escribe rutas anidadas sin conocer el esquema |
| Sin registro de mutaciones | Ninguno: la asignación de modelo vive en su propio store, no en el journal | Pisar el artefacto deja de ser un riesgo para el ownership porque el journal nunca se entera de esa preferencia |

### Formato

```json
{
  "schema": "pegasus-harness/journal/v4",
  "pegasus_version": "4.0.0",
  "installs": [
    {
      "cli": "opencode",
      "installed_at": "2026-08-14T00:41:08Z",
      "release": {
        "version": "4.0.0",
        "content_digest": "sha256:1a2b…",
        "catalog_digest": "sha256:3c4d…"
      },
      "entries": [
        {
          "id": "skill:sdd-apply",
          "kind": "file",
          "target": "/home/serg/.config/opencode/skills/sdd-apply/SKILL.md",
          "after_digest": "sha256:5e6f…",
          "mode": "0644",
          "ownership": "owned",
          "created_at": "2026-08-14T00:41:09Z"
        },
        {
          "id": "agent:sdd-apply",
          "kind": "config-key",
          "target": "/home/serg/.config/opencode/opencode.json",
          "pointer": "/agent/sdd-apply",
          "after_digest": "sha256:7a8b…",
          "ownership": "owned",
          "created_at": "2026-08-14T00:41:09Z"
        }
      ],
      "links": [
        {
          "id": "cbm",
          "target": "/usr/local/bin/codebase-memory-mcp",
          "ownership": "non-owning-link"
        }
      ]
    }
  ]
}
```

### Dónde vive

```
~/.local/share/pegasus-harness/journal-v4.json     # 0600, en un directorio creado 0700
```

El nombre lleva la versión del esquema. v3 escribía `journal-v3.json` en el mismo directorio, y v4 es una instalación limpia al lado de v3, no una reescritura de su estado: nunca abre ni pisa el archivo de v3.

El directorio se **crea** con permisos `0700`. Si ya existía —porque v3 lo creó con `0755`— conserva los suyos: endurecerlo sería mutar algo que esta instalación no creó, y el archivo en `0600` ya protege el contenido.

Esa ruta está escrita a mano y no consulta el entorno. La unidad 8 le pone un resolutor y la mueve a la convención de cada plataforma, con el journal y las dependencias en el mismo lugar; los permisos y la política del store no cambian. Cuando eso ocurra, la coincidencia de directorio con v3 desaparece y con ella el caso del `0755` heredado.

Quien resuelve esa ruta es `FileJournalStore`, detrás del puerto `JournalStore`. Escribe a través del puerto `FileSystem`, así que la política del store —quién puede escribir, qué se puede escribir, qué significa un archivo dañado— se prueba sin un home real. Un journal ilegible **no** es un journal vacío: el store falla ruidosamente, porque tratarlo como vacío dejaría huérfano todo lo ya instalado.

### Lo que el desinstalador deja atrás

Retirar no reescribe un archivo de configuración si no cambió nada en él: la indentación del usuario es suya y no se gasta sin motivo.

Queda un residuo conocido y aceptado: si el archivo de configuración del CLI **no existía** antes de instalar, Pegasus lo crea y al desinstalar lo deja vacío (`{}`). El journal registra claves, no la existencia del archivo, así que no hay forma de saber que fue nuestro sin agregar una entrada para el archivo mismo — y esa entrada chocaría con las claves que viven adentro. Un archivo de configuración vacío es inofensivo: el CLI lo lee como configuración por defecto. Si alguna vez molesta, la solución es registrar la creación del archivo como un hecho aparte del de sus claves.

### Reglas invariantes

- [ ] Todo `target` está contenido dentro del home del usuario
- [ ] El journal lo escribe el usuario dueño del home, nunca root
- [ ] Escritura atómica: archivo temporal, `fsync`, `rename`
- [ ] Al desinstalar, todo lo que el journal reclama se borra sin mirar si el usuario lo tocó, salvo los appends, donde la huella no alcanza para decidir si el ítem sigue siendo nuestro y el resultado es `unaccounted` (ver "La excepción: punteros que agregan a una lista")
- [ ] Un `link` nunca se borra: Pegasus no es dueño de dependencias preexistentes
- [ ] Reinstalar nunca reduce lo que el journal ya poseía
- [ ] El journal se consulta antes de escribir el primer artefacto, no después del último

---

## Configuración de modelos

### De dónde salen proveedores y modelos

El adapter de OpenCode lee tres archivos. No levanta un servidor ni parsea salida del CLI.

| Fuente | Ruta | Aporta |
|--------|------|--------|
| Catálogo | `~/.cache/opencode/models.json` | Proveedores, modelos, costo, límites, `tool_call`, `reasoning` |
| Credenciales | `~/.local/share/opencode/auth.json` | Qué proveedores tienen sesión OAuth |
| Config | `~/.config/opencode/opencode.json` → clave `provider` | Proveedores personalizados del usuario |

Un proveedor se ofrece si cumple **alguna** de estas condiciones:

- Tiene credencial en `auth.json`
- Tiene todas sus variables de entorno seteadas (`ANTHROPIC_API_KEY`, etc.)
- Está declarado como proveedor personalizado en la config
- Es el proveedor integrado del propio CLI

De cada proveedor se ofrecen **solo los modelos con `tool_call: true`**. Un modelo sin tool calling no puede ejecutar una fase SDD.

Si el archivo de catálogo no existe todavía (el usuario instaló el CLI pero nunca lo abrió), el adapter devuelve catálogo vacío y la TUI explica qué hacer. No es un error.

### Modelo de asignación

```python
@dataclass(frozen=True)
class ModelAssignment:
    provider_id: str      # "anthropic"
    model_id: str         # "claude-sonnet-5"
    effort: str | None    # None = default del proveedor
```

Se persiste como `provider/model`, más un campo de esfuerzo cuando el modelo declara variantes de razonamiento.

### Estado inicial

Ningún agente trae modelo asignado. La tabla arranca con todos en "sin modelo", y un agente sin configurar simplemente no tiene el campo. Esto preserva la política vigente de no fijar modelos por agente: configurar es una decisión explícita del usuario, y siempre reversible.

### El prompt de un agente es corto

Un prompt de agente lleva solo lo que ese agente no puede permitirse ignorar aunque nunca llegue a leer nada más: su identidad, sus innegociables y su contrato de salida. Todo lo procedimental — la secuencia de pasos, las plantillas de salida, los protocolos, los gates — vive en la skill de esa fase y el orquestador se la pasa como ruta al delegar.

La razón es medible. En una instalación real de la línea v3, los nueve prompts de fase SDD eran copias completas de su skill y sumaban unos 21.000 tokens que entraban en contexto antes de que el agente hiciera nada. El único que estaba bien escrito, `sdd-verify`, gastaba 159 tokens para el mismo tipo de trabajo. Y como el orquestador además le pasa al subagente la ruta de su propia skill, un prompt que ya es esa skill hace que el agente lea otra vez lo que ya tiene.

De ahí sale una regla de contenido: **un descriptor de agente cuyo cuerpo supere unos pocos párrafos indica que hay procedimiento donde debería haber identidad.**

### Qué es el system prompt y qué es un agente

El archivo de instrucción global que llegó desde v3 mezclaba dos cosas: reglas y protocolos que obligan a cualquier agente, y la personalidad y el rol de un agente en particular. En v4 se parte:

| Parte | Va a | Alcance |
|-------|------|---------|
| Reglas de trabajo, alcance de persona, carga contextual de skills, protocolo de memoria persistente, cierre de sesión | `system-prompt/` | Todos los agentes, en toda sesión |
| Idioma de la respuesta: cuál usar y cuándo no cambiarlo | `system-prompt/` | Todos los agentes, en toda sesión |
| La voz, en sus ocho secciones: `Rules`, `Personality`, `Language`, `Speech patterns`, `Tone`, `Philosophy`, `Expertise`, `Behavior` | `agents/king-pegasus.md` | Ese agente |

El criterio no es "reglas arriba, estilo abajo": es a quién obliga cada cosa. La mayoría de las reglas de trabajo — no agregar atribución de herramientas a un commit, verificar antes de afirmar — tienen que obligar a cualquier agente, no solo al que casualmente cargaba ese archivo como prompt. Pero una regla sobre cómo trabaja una voz en particular es de esa voz: `Work out loud or not at all` vive en `king-pegasus.md` a propósito, porque como regla global sería falsa — los agentes implementadores escriben en silencio para satisfacer una spec, y eso es exactamente lo que se les pide. El ejemplo anterior acá era `Never build after changes`, que vivía en ese mismo archivo por la misma razón antes de que la reconversión de la voz lo eliminara (ver `Deudas resueltas`): la skill `sdd-verify` exige correr el build y registrar su hash, así que una prohibición global de compilar habría contradicho algo que embarcamos.

`Language` se parte por esa misma razón. La mitad neutral — en qué idioma responder, cuándo no cambiarlo, que una respuesta en inglés sea inglés hasta en el saludo — obliga a todos los agentes y vive en `system-prompt/`; el color — Rioplatense con voseo, la misma calidez en inglés — es de esa voz y se queda en su archivo.

### Agentes configurables en 4.0.0

Los 10 de la línea SDD, más los dos de coordinación:

```
sdd-init      sdd-explore    sdd-propose    sdd-spec      sdd-design
sdd-tasks     sdd-apply      sdd-verify     sdd-archive   sdd-onboard
pegasus-orchestrator         king-pegasus
```

En v3.1.2 se embarcan los 10 prompts SDD pero solo uno está cableado como agente. v4 corrige eso: cada fase existe como subagente real, con su prompt y su modelo configurable.

---

## Interfaz de usuario

La TUI se dibuja con `curses`, de la biblioteca estándar. No agrega ninguna dependencia, y por lo tanto no agrega nada que el empaquetado de la unidad 4 tenga que fijar con hash ni sumar al zipapp. Las pantallas que siguen son listas verticales con un cursor y teclas de una letra: no piden color, ni layout anidado, ni nada que justifique traer un paquete —y menos uno que arrastre un segundo— para dibujarlas.


### Menú principal

La pantalla se dibuja en inglés — el idioma de todo el texto de la TUI, sin excepción para esta pantalla ni ninguna otra.

```
Pegasus Harness 4.0.0

  ▸ Install
    Configure models
    Status and diagnostics
    Uninstall
    Exit
```

### Instalar

Detecta CLIs soportados y presentes. Selección de a uno.

```
Where would you like to install Pegasus?

  ▸ OpenCode          ~/.config/opencode        full
```

Elegido el CLI, muestra la vista previa —el mismo reporte que produce `install --dry-run`, con un aviso explícito de que todavía no se escribió nada— y sólo confirmarla cruza el punto sin retorno:

```
Install · OpenCode

PREVIEW — nothing has been written yet.

...

enter: install now · esc: back, nothing written
```

No hay confirmación por dependencia individual dentro de la TUI: qué servidores MCP entran ya se decidió con `--mcp` antes de llegar a esta pantalla (ver "Paridad con flags").

### Estado y diagnóstico

Muestra el mismo reporte que `doctor --json`. Desde acá, y sólo acá, se llega a `restore`: elegir la única acción de esta pantalla abre la lista de generaciones de snapshot que todavía se pueden leer. No hay una entrada de `restore` en el menú principal — es una acción sobre lo que el diagnóstico ya mostró, no una entrada propia.

### Desinstalar

Selecciona, de los CLIs donde el journal registra una instalación propia, cuál desinstalar. La confirmación es una vista previa de qué se va a borrar (resumida si son muchos ítems), con el cursor abierto por defecto sobre "Cancel": la opción destructiva nunca es la que queda seleccionada al entrar a la pantalla.

```
Uninstall · OpenCode

About to remove 3:
  skill:sdd-apply → ...
  agent:sdd-apply → ...
  ...

  ▸ Cancel — leave it installed
    Confirm — remove it
```

`restore`, alcanzado desde "Estado y diagnóstico", pide la misma confirmación con el cursor sobre "Cancel".

### Configurar modelos

Cuatro pasos, con opción de volver en cada uno, y todo lo elegido queda **acumulado** en la propia pantalla hasta que se confirma de una sola vez -- no hay una escritura por cada asignación.

```
CLI → agente → proveedor → modelo → [esfuerzo]
```

Terminar la caminata (un modelo llano, o un modelo de razonamiento más su esfuerzo) no escribe nada: guarda la elección en el estado de la propia pantalla y vuelve a la lista de agentes, igual que tildar una fila no escribe nada en `McpSelectionScreen`. `d` hace lo mismo del otro lado: en vez de sacar la asignación ahí mismo, la marca para sacarla. La lista de agentes muestra las dos cosas por separado -- lo que ya está aplicado y lo que está pendiente de confirmar -- y una fila `Confirm` después del último agente es la única que efectivamente escribe: aplica todo lo acumulado, asignaciones y remociones por igual, en un solo `cli.models_apply`, y por lo tanto un solo `install()` y una sola generación de snapshot.

```
Models · OpenCode

  Agent                    Current model                Staged change
  ▸ pegasus-orchestrator   (no model)
    sdd-apply              anthropic/claude-sonnet-5 · high  → anthropic/fast-model
    sdd-verify             (no model)                   → (remove)
    …
    Confirm — apply staged changes

  enter: configure, or confirm to apply · d: stage a removal · esc: back, discards staged changes
```

Salir sin confirmar (`esc` en la lista de agentes) descarta todo lo acumulado: el footer ya lo dice, y no hace falta ningún otro aviso porque nada llegó a escribirse. Configurar cuatro agentes en una sola sentada es, ahora, un `install()` y una generación -- antes eran cuatro de cada uno, con cuatro avisos de activación por separado, exactamente la misma tormenta que `McpSelectionScreen` ya resolvió para su propio Continue.

### Paridad con flags

La TUI no puede hacer nada que los flags no puedan. Esta regla protege `INSTALL_BY_AGENT.md`, que es el diferencial de Pegasus: instalación conducida por un agente.

```bash
pegasus                                          # TUI
pegasus install --cli opencode --mcp context7 --mcp engram
pegasus models set --cli opencode --assign sdd-apply=anthropic/claude-sonnet-5 --effort sdd-apply=high
pegasus models unset --cli opencode --agent sdd-apply
pegasus uninstall --cli opencode
pegasus doctor --json
```

Un test de contrato verifica que cada acción de la TUI tenga su comando equivalente.

#### Qué existe hoy

Nueve subcomandos: `install`, `update`, `upgrade`, `uninstall`, `doctor`, `restore`, `models`, `mcp` y `directory`, con `--json` en todos y `--dry-run` en `install`, `update` y `upgrade`; `-V` / `--version` responde antes del subcomando y no abre nada. El corte numerado entregó `install`, `uninstall`, `doctor`, `restore` y `models`; los otros cuatro llegaron después — `mcp` y `directory` tienen su propia sección en "Lo que se agregó después del corte", y `update` y `upgrade` entraron juntos en 5.11.0, separando actualizar *la instalación* de actualizar *el programa*.

- `install --cli <id>` acepta `--mcp ID[=CLAVE]` (repetible): un servidor no nombrado no se instala, y la forma con clave concede sus herramientas y embarca su convención contra un servidor que la instalación ya corre bajo esa clave, sin obtener ni configurar nada.
- `update --cli <id>` reaplica la selección que esa instalación ya tiene registrada —servidores atados incluidos, más las claves y los directorios otorgados—, sin ningún flag de selección. No hay una segunda implementación de colocar artefactos: reconstruye qué habría sido `--mcp` leyendo el journal y delega en `install`.
- `upgrade` es el único que no lleva `--cli`, porque no toca la instalación de ningún CLI: reemplaza el propio binario `pegasus` en ejecución por el último publicado, verificando el checksum antes de un único rename atómico.
- `uninstall --cli <id>` retira lo que el journal reclama para ese CLI.
- `doctor` acepta `--start-mcp-servers`, la única forma en que deja de ser de sólo lectura.
- `restore [generación]` tampoco lleva `--cli`: una generación es lo que tocó un comando, no la instalación de un CLI.
- `models set` / `models unset` / `models list` asignan, quitan y listan el modelo de un agente.
- `mcp grant` / `mcp revoke` / `mcp list` manejan las claves de servidores MCP que la persona administra por su cuenta, parejo para todos los agentes.
- `directory grant` / `directory revoke` manejan un directorio de trabajo fuera del worktree, también para todos los agentes.

Cada reporte declara su esquema `pegasus/cli-report/v1`.

Seis cosas que la CLI hace y conviene no perder:

- **Pregunta antes de hacer.** El journal se consulta con `ensure_writable()` **antes** del primer artefacto. Una negativa descubierta al final llegaría con los artefactos ya en disco y sin registro: una instalación que existe y no se puede desinstalar, el peor resultado que este motor puede producir. Preguntar primero lo convierte en un mensaje y un home intacto.
- **El preflight pregunta las dos cosas: si se puede escribir y si se puede leer lo que ya hay.** Un journal que no se puede leer es uno que no se puede extender, y descubrirlo después de colocar los artefactos los dejaría en disco sin nada que los registre — con `doctor` fallando contra ese mismo journal ilegible, así que no quedaría forma de enterarse de que están.
- **`ensure_writable()` es un preflight, no una garantía.** Rechaza root y homes ajenos, que son las causas previsibles. No puede prometer que el guardado posterior funcione: el disco se puede llenar, los permisos pueden cambiar entre medio, puede haber cuota. Por eso el camino de falla al registrar tiene que ser correcto igual, y no solo improbable.
- **Si igual no se puede registrar, se retira lo instalado.** Y se informa lo que no pudo volver atrás: Pegasus posee claves dentro de un archivo de configuración, nunca el archivo, así que uno que tuvo que crear sobrevive vacío. Inofensivo, pero afirmar un deshecho limpio sería una mentira chica en el único reporte que alguien lee cuando algo ya salió mal.
- **El rollback deshace esta corrida, nunca lo que corridas anteriores ya poseían.** Hay dos vistas de la misma instalación y confundirlas sale caro: la **acumulada** es la que se registra —todo lo que ese CLI posee, viejo y nuevo— y la **colocada** es solo lo que esta corrida escribió. Solo la segunda puede tocarse al deshacer. Una reinstalación no crea nada, así que no hay nada que deshacer; retirar la vista acumulada borraría una instalación que funciona mientras el journal —que no se llegó a escribir, porque escribirlo es lo que falló— sigue afirmando que está entera. Es la misma mentira que los artefactos huérfanos, apuntando para el otro lado.
- **Reinstalar no reduce lo que el journal ya poseía.** La segunda corrida no crea nada, porque todo lo que quiere ya está: su propio trabajo de la primera. Reemplazar el registro con ese resultado vacío dejaría huérfanos para siempre todos los artefactos que la primera corrida colocó —103 en una instalación de hoy en OpenCode sin ningún MCP seleccionado, medida contra un HOME descartable; el número crece con la selección y cambia con cada release, que es justamente por qué el argumento no depende de él—, sin nada que pruebe que fueron nuestros. Las entradas previas se conservan y las nuevas se suman.

#### Actualizar es reinstalar, y `update` es reinstalar sin tener que repetir la selección

Durante 4.0.0 y 4.1.0 no hubo comando de actualización aparte: reinstalar era la única forma. Hoy existe `pegasus update --cli <id>`, pero el mecanismo no cambió — sigue siendo `install` por debajo. Lo que `update` agrega es no tener que recordar la selección: un `install` a secas no nombra ningún servidor, y un servidor no nombrado se retira, así que actualizar con `install` exige repetir exactamente los `--mcp` de la primera vez, y la selección de un servidor *atado* ni siquiera se puede leer de vuelta desde la configuración renderizada, porque una atadura no escribe `/mcp/<id>` ahí. `update` reconstruye esa selección desde el journal y delega (`update`, `src/pegasus/cli.py`).

Lo que sigue vale para los dos, porque los dos terminan en el mismo planner, que distingue las tres respuestas posibles por artefacto (`planner.plan`, `_file_step`/`_key_step`, `src/pegasus/core/planner.py`).

- **El contenido cambió bajo el mismo id:** se reescribe. Una dirección que el journal reclama se pisa sin preguntar si el usuario la tocó — esa pregunta se retiró en la unidad 9 —, y sólo se escribe si lo que hay ahora difiere de lo que se quiere: `_file_step` compara el digest (y el modo, para un ejecutable) contra lo leído del disco, y sólo devuelve `UPDATE` cuando discrepan.
- **El contenido es idéntico:** se deja quieto. Mismo digest y mismo modo es `UNCHANGED`; reinstalar no repite una escritura que no hace falta.
- **La dirección está ocupada por algo que el journal no reclama:** es colisión, y se saltea. `_file_step` devuelve `SKIP` cuando no hay entrada del journal para esa ruta, o la entrada es de otro tipo o apunta a otro destino — la única situación en la que reinstalar de verdad se niega a escribir.

Un artefacto que un release más nuevo **deja de embarcar** sí se retira. `planner.retirements` calcula, para cada entrada que el journal ya tiene, si el render de esta corrida todavía la pide; la que no aparece entre los artefactos actuales es una diferencia de conjuntos por id, sin tocar disco (`retirements`, `planner.py`). `cli._install` pasa ese conjunto — menos las entradas `dependency-tree`, que se recalculan aparte contra los servidores MCP que la corrida efectivamente mantiene — a `planner.retire`, que sí borra: un archivo se quita si existe, una clave se saca del documento, y cada handler por tipo marca el id como `removed` (`retire`, `_retire_files`, `RETIRE_HANDLERS`, `planner.py`; el llamado desde `cli.py` alrededor de la variable `retirements`). El journal se actualiza para reflejar sólo lo que `retire` confirmó haber sacado, nunca la intención: un id que no pudo confirmarse sigue en el journal para que una corrida posterior termine el trabajo.

Lo que sí es una edición a mano del usuario sobre una dirección que Pegasus posee: se reescribe igual — la política de la unidad 9 no distingue este caso de cualquier otro `UPDATE`, así que el producto gana sin pedir permiso —, pero desde que existe `Plan.overwritten` deja de ser silencioso. Decidir `UNCHANGED` contra `UPDATE` ya obliga a leer la dirección, así que el paso carga lo que encontró ahí (`found`), y que eso discrepe del digest que el journal tenía registrado (`entry.after_digest`) es exactamente la definición de una edición a mano — la misma comparación que `doctor` llama drift, hecha en el momento en que la edición está por gastarse en vez de antes o después. `Plan.overwritten` filtra los `updates` con esa forma, y tanto `install` como `--dry-run` lo reportan aparte, a tiempo para que alguien cambie de idea en el dry run y a tiempo para saber qué se perdió después de uno real. Lo que protege ese contenido no es un chequeo que impida la escritura — no lo hay — sino el snapshot que la unidad 9 toma antes de escribir: `restore` puede devolver la versión de la persona, dentro de la ventana que la retención de 20 generaciones guarda. Los `append` quedan afuera de este reporte a propósito: se los localiza por el digest registrado, así que un valor que discrepa no se encuentra ahí y "alguien editó el nuestro" es indistinguible de "alguien borró el nuestro y agregó el suyo".

Esa pregunta —si convenía un comando `update` separado de `install`— quedó contestada después del corte, y por una razón que el diseño original no tenía a la vista: no era una diferencia de mecanismo sino de memoria. La actualización necesitaba recordar la selección, no escribir distinto. Por eso `update` no es una segunda implementación de nada: es `install` con los flags que el journal ya sabía.

#### Una inconsistencia conocida

`detect()` es la única operación de disco que **no pasa por el puerto `FileSystem`**: el adapter resuelve con `shutil.which` contra el PATH y un `is_dir()` real. Eso hace que la detección mire la máquina donde corre, sin importar lo que se le diga al puerto, y que no se pueda probar sin tocar el disco de verdad. Arreglarlo cambia la firma de `CliAdapter.detect` y el puerto necesitaría saber buscar en el PATH, así que es una unidad de trabajo aparte.

---

## Estructura del repositorio

```
pegasus-harness/
├── pyproject.toml
├── src/pegasus/
│   ├── __main__.py
│   ├── cli.py                     # flags, modo desatendido
│   ├── core/                      # 16 módulos, ninguno con nombre de CLI adentro
│   │   ├── content.py             # carga y valida el núcleo de contenido
│   │   ├── types.py               # descriptores, Artifact, Layout, Detection
│   │   ├── registry.py            # registro de adapters, falla cerrado
│   │   ├── planner.py             # plan, apply, retire, rollback
│   │   ├── journal.py             # journal v4
│   │   ├── ownership.py           # huellas, colisiones, mutaciones
│   │   ├── snapshot.py            # lo que había antes de escribir
│   │   ├── dependencies.py        # materializar un servidor `download` o `npm`
│   │   ├── mcp_handshake.py       # el `initialize` y la clasificación de su respuesta
│   │   ├── model_assignments.py   # preferencias de modelo por agente
│   │   ├── model_catalog.py       # qué modelos alcanza esta máquina
│   │   ├── catalog.py             # el catálogo embarcado
│   │   ├── codecs.py              # JSON, TOML, YAML como un solo puerto
│   │   ├── pointer.py             # direcciones dentro de un documento
│   │   ├── frontmatter.py         # el parser propio, sin dependencias
│   │   └── placeholders.py        # el vocabulario cerrado que un cuerpo puede pedir
│   ├── ports/
│   │   ├── cli_adapter.py
│   │   ├── filesystem.py
│   │   ├── journal_store.py
│   │   ├── snapshot_store.py
│   │   ├── model_assignment_store.py
│   │   ├── downloader.py
│   │   ├── npm_installer.py
│   │   └── mcp_process.py
│   ├── adapters/
│   │   └── opencode/              # el único adapter que existe
│   │       ├── adapter.py
│   │       ├── layout.py
│   │       ├── render.py
│   │       ├── models.py          # proveedores y modelos
│   │       ├── manifest.py
│   │       └── assets/            # plugins y binarios que viajan con el adapter
│   ├── infra/                     # una implementación real por puerto, POSIX
│   │   ├── fs_posix.py
│   │   ├── journal_store_file.py  # el journal como archivo, sobre el puerto FileSystem
│   │   ├── snapshot_store_file.py
│   │   ├── model_assignment_store_file.py
│   │   ├── downloader_http.py
│   │   ├── npm_installer_subprocess.py
│   │   └── mcp_process_subprocess.py
│   ├── tui/
│   │   ├── app.py
│   │   ├── navigator.py           # las pantallas y el paso entre ellas
│   │   ├── session.py
│   │   └── view.py
│   └── content/                   # ← el núcleo, agnóstico
│       ├── skills/
│       ├── agents/
│       │   └── mcp/               # la mitad ambiente de cada servidor, y sus overrides
│       ├── commands/
│       ├── mcp/                   # un descriptor por servidor, con su convención adentro
│       └── system-prompt/
│           └── mcp/               # la mitad ambiente, para el prompt de sistema
├── tools/
│   ├── build_catalog.py
│   ├── build_zipapp.py            # empaqueta el paquete en el zipapp ejecutable
│   ├── build_release_evidence.py  # certifica el zipapp y su checksum contra el commit
│   ├── build_release_manifest.py  # reproduce la evidencia de los tags v3.1.x
│   ├── check_docs_links.py
│   └── pegasus_skill_registry.py
├── tests/
└── docs/
```

El contenido vive dentro del paquete, alineado con la decisión previa de una única fuente canónica bajo `src/`. Eso permite distribuirlo como paquete sin rutas relativas frágiles.

---

## Contratos versionados

Cada contrato tiene esquema propio y versión. Un cambio incompatible sube la versión; el motor rechaza lo que no reconoce.

| Contrato | Esquema | Qué fija |
|----------|---------|----------|
| Manifiesto de capacidades | `pegasus/capability-manifest/v1` | Qué soporta cada adapter |
| Catálogo de artefactos | `pegasus/artifact-catalog/v4` | Salida generada del render, con huellas |
| Journal de ownership | `pegasus/journal/v4` | Estado de instalación |
| Asignación de modelo | `pegasus/model-assignment/v1` | Proveedor, modelo y esfuerzo por agente |
| Reporte de la CLI | `pegasus/cli-report/v1` | Salida JSON de `install`, `uninstall` y `doctor` |

La forma de skills, agentes, comandos, prompts, MCPs y políticas la valida el cargador de contenido (`pegasus.core.content`), no un esquema versionado con identificador de cable propio: no hay ningún `pegasus/content-descriptor/vN` que ningún código emita o valide, así que esta tabla no vuelve a listarlo.

---

## Postura de seguridad

Todo lo que v3 ya garantiza se mantiene, y se extiende a las dependencias nuevas de Python.

| Garantía | v3 | v4 |
|----------|----|----|
| Instalación aditiva, nunca pisa archivos del usuario | Sí | Sí |
| Payload verificado con SHA-256 | Sí | Sí, sobre el catálogo generado |
| Dependencias con versión fija, sin `npx` ni `latest` | Sí | Sí |
| Sin ejecución como root | Sí | Sí |
| Rollback que preserva lo modificado por el usuario | Sí | Sí, pero por otro camino: el journal ya no preserva nada, la vuelta atrás es el snapshot tomado antes de escribir, y tiene un horizonte — pasada la retención, el original ya no está en ningún lado |
| Dependencias Python con hashes | — | `pip install --require-hashes` |
| Detección sin ejecutar binarios de terceros | — | Sí |

La verificación de integridad del payload deja de escribirse a mano: el catálogo se genera y CI falla si el catálogo commiteado no coincide con el generado desde el contenido.

---

## Qué queda fuera de 4.0.0 y 4.1.0

Explícitamente fuera de alcance, para que el corte sea revisable:

- **Windows.** La arquitectura lo habilita (`FileSystem` como puerto, TUI portable, Python multiplataforma), pero no se entrega en 4.0.0.
- **Adapters de Claude Code y Codex.** El esqueleto `_template/` queda listo; los adapters reales no.
- **Migración automática desde v3.1.x.** El camino es desinstalar v3 e instalar v4.
- **Skills personales del autor.** Siguen fuera del payload, como hoy.

---

## Riesgos conocidos

| Riesgo | Mitigación |
|--------|------------|
| El catálogo de modelos del CLI puede no existir todavía | Catálogo vacío no es error; la TUI explica cómo poblarlo |
| El formato de config del CLI puede cambiar entre versiones | El adapter concentra el daño; solo se toca un directorio |
| Dependencias Python amplían la superficie de ataque | Versiones y hashes fijos, verificados en instalación y en CI |
| Un adapter futuro puede declarar capacidades que no cumple | El registry falla cerrado al registrar |
| El rediseño puede perder garantías de v3 sin que se note | Tabla de postura de seguridad como checklist de verificación |

---

## Corte de entrega propuesto

Ocho unidades numeradas, más la unidad 0 de demolición. Cada una tiene tests propios y límite de rollback. El detalle de tareas se define aparte.

**El número de unidad es un identificador estable, no un puesto en la cola.** Las unidades 0 a 6 se numeraron al escribir este corte; las unidades 7 y 8 se agregaron después, cuando el trabajo las descubrió, y ninguna de las dos espera a la 4. Los números no se renumeran, para que toda referencia ya escrita siga apuntando a la misma unidad. El orden real de trabajo está más abajo.

| # | Unidad | Entrega verificable | Estado |
|---|--------|---------------------|--------|
| 0 | Demolición y reubicación | El repositorio queda ordenado, sin motor v3 y sin lógica nueva | Entregada |
| 1a | Tipos, punteros, códecs, puerto y registry | El motor genérico existe y no conoce ningún CLI | Entregada |
| 1b | Carga de contenido, adapter OpenCode y catálogo | Genera en memoria el catálogo del contenido presente, con digests deterministas | Entregada |
| 2 | Motor de instalación, journal v4, rollback | Paridad funcional con v3.1.2 en modo desatendido | Entregada |
| 3 | Los 12 agentes cableados con sus prompts, y el contenido normalizado | Los 10 SDD existen como subagentes reales | Entregada |
| 4 | Launcher, empaquetado de un solo archivo | `pegasus` disponible en el PATH tras instalar: un único `zipapp` con shebang y bit ejecutable, construido por `tools/build_zipapp.py`, y `tools/build_release_evidence.py` atando el archivo y su `.sha256` al commit que los produjo. Sin venv privado ni shim: con cero dependencias un venv no aísla nada, y con shebang más bit ejecutable el archivo se ejecuta solo, así que el launcher, el provisioner de venv y su puerto se quedaron sin sujeto y se retiraron. `INSTALL.md` documenta el recorrido de punta a punta y deja constancia de qué se corrió en esta verificación y qué no —el único paso no ejecutado es la descarga con red real, prohibida en este entorno | Entregada |
| 5 | TUI: menú principal e instalación | Instalación completa sin escribir un flag: menú de cinco entradas (`Install`, `Configure models`, `Status and diagnostics`, `Uninstall`, `Exit`), instalación con vista previa (`InstallPlanScreen`, el mismo reporte de `install --dry-run`) separada del punto sin retorno | Entregada |
| 6 | TUI: configuración de modelos | Asignar y quitar modelo por agente, con la preferencia guardada en el estado propio de Pegasus: la caminata de cuatro pasos (`ModelsScreen`) llama a `cli.models_set`/`cli.models_unset`, que escriben en el store real de asignaciones | Entregada |
| 7 | Actualización de una instalación existente | Reinstalar sobre una instalación propia actualiza el payload. La segunda mitad de lo entregado —preservar y reportar lo que el usuario reescribió— la reemplazó la unidad 9 | Entregada |
| 8a1 | Categoría `mcp/`, descriptor y render del servidor | Un MCP remoto se instala de verdad, con su convención embarcada y su permiso concedido | Entregada |
| 8a2 | Selección del usuario y reversibilidad | `--mcp` decide qué servidores se instalan, y dejar de nombrar uno lo retira. El retiro salió genérico: alcanza a cualquier artefacto que el journal reclame y el render ya no produzca | Entregada |
| 8b1 | El directorio propio de Pegasus y su resolutor | El journal, los snapshots y lo que venga cuelgan de un único lugar que la plataforma decide (`FileSystem.data_dir`): `journal_store_file.py`, `snapshot_store_file.py` y `model_assignment_store_file.py` resuelven el mismo directorio a través del puerto `FileSystem` | Entregada |
| 8b2 | Contención: el registry y el catálogo aprenden el segundo territorio | Un artefacto en el directorio propio deja de parecer una fuga: `catalog.Territory` reconoce `config_dir` y `CANONICAL_DATA_DIR` al calcular el catálogo. El chequeo de `registry` sobre `own_artifacts` queda a propósito ceñido al `config_dir` del adapter —una dependencia la coloca el motor, nunca un adapter, así que ensanchar ese guard no cerraría ningún hueco real | Entregada |
| 8b3 | El journal sabe reclamar una dependencia materializada | `uninstall` deja de poder olvidarse un binario en silencio: `journal.KINDS` suma `dependency-tree`, y `planner._retire_dependency_trees` lo retira al desinstalar | Entregada |
| 8b4 | La forma `download` | Un servidor que publica binario queda disponible, con SHA-256 propio verificado antes de que el archivo llegue a su lugar (`core/dependencies.materialize`). También extrae un `.tar.gz` con guarda contra miembros que se escapan del directorio (`tarfile.data_filter`): `engram` ya se instala así, con checksum y `archive_members` fijados en su descriptor | Entregada |
| 8b5 | La forma `npm` | El motor sabe correr `npm ci` contra un lockfile que sintetiza para un único paquete (`core/dependencies.materialize_npm`), con tests propios. Pero ningún descriptor real la usa todavía: `engram` viajó por `download`, no por `npm`, y CBM sigue sin descriptor —su única fuente en este repo es un tarball vendorizado sin URL publicada. La forma existe; lo que promete su nombre —un servidor npm instalado de verdad— no tiene todavía a quién aplicarse | Entregada |
| 9 | El digest deja de ser permiso; snapshot, `restore` y retención | Instalar y desinstalar pisan lo que el journal reclama, y `restore` devuelve el estado exacto anterior al último comando | Entregada |
| 10 | El puerto de filesystem puede decir "no puedo saberlo" | Una ruta que existe y no se puede leer deja de hacerse pasar por ausente: `exists` y `list_dir`, y los trece sitios que les creen | Entregada |
| 11 | Los permisos dejan de ser un octal en el núcleo | `FileArtifact` dice `executable`, no un modo; los bits nacen en `mode_for` del lado de la plataforma; un solo guard `writable_on_behalf_of_owner` reemplaza los dos duplicados; un test guardián sostiene que ningún literal de permiso vuelva a `core/` ni `ports/` | Entregada |

La unidad 1b genera el catálogo **del contenido presente**, no del contenido final: los descriptores de los 10 agentes SDD y las categorías `mcp/` y `policies/` llegan en unidades posteriores.

### Unidad 7 — Actualización de una instalación existente

El planner responde dos preguntas por artefacto: si algo ocupa la dirección, y si el journal la reclama como propia. Lo que el journal reclama se sobrescribe, y sólo si el contenido nuevo difiere del que ya está — si es idéntico no es trabajo, y se deja quieto.

La unidad 9 sacó de acá dos preguntas más que esta unidad había traído: si el artefacto fue cambiado a propósito desde entonces, y si los bytes que hay son los que el journal registró. Las dos usaban el digest para decidir si escribir, y las dos se fueron con él. Lo que el usuario haya reescrito sobre una dirección nuestra se pisa, y lo que lo protege es la copia que se toma antes de escribir, no una huella que se consulta al escribir.

Un append es la versión difícil de la pregunta. No tiene dirección propia, así que su item se busca por huella y el valor nuevo lo reemplaza donde está: appendear en su lugar dejaría dos nuestros y correría los del usuario. Un item que la lista ya no tiene vuelve a ser una creación — la ausencia no es un veredicto.

El rollback distingue las dos colocaciones: una creación se deshace removiendo, una actualización restaurando la versión anterior.

### Unidad 8 — Distribución de MCPs

Ningún binario de MCP se vendoriza ni se compila desde este repositorio: sostener la compilación para varios pares SO/arch es exactamente el costo que este diseño evita. **No vendorizar significa que la release no lleva binarios ajenos, no que no se descargue nada**: la descarga ocurre en la máquina del usuario, durante la instalación, y nunca después. Esta unidad es la que trae la categoría de catálogo `mcp/` que la unidad 1b anticipa.

Sobre cualquiera de los mecanismos van las dos garantías que no se relajan: **versión fija, nunca `latest`**, e **integridad verificada antes de dejar el artefacto en su lugar**. La primera la sostenemos nosotros en el descriptor, siempre. La segunda depende del mecanismo, y el diseño lo dice en voz alta en vez de fingir uniformidad.

#### Tres formas, declaradas por el descriptor

Los MCPs del producto no se distribuyen todos igual, y forzarlos a un mecanismo único sería inventar un problema. El descriptor declara cuál le toca a cada uno.

| Forma | Qué hace la instalación | Integridad | Red al arrancar el agente |
|-------|-------------------------|------------|---------------------------|
| `remote` | Escribe una URL en la configuración del CLI | La del endpoint | Sí, por naturaleza: el servidor es remoto |
| `npm` | Materializa el paquete pineado en el directorio propio de Pegasus | La cadena del registry: hash de integridad del tarball y, cuando existe, atestación de provenance | Ninguna |
| `download` | Baja el activo del par SO/arch y verifica su SHA-256 contra el checksum publicado | Nuestra, obligatoria, fail-closed | Ninguna |

Que la integridad de la forma `npm` la sostenga el registry y no nosotros es una decisión, no un descuido: verificar un hash propio exigiría materializar el paquete a mano y renunciar a una cadena que ya hace ese trabajo mejor —y que, en el caso de los paquetes que envuelven un binario nativo, lo verifica una segunda vez contra el checksum de su propio release.

#### Por qué el comando configurado nunca es `npx`

La tentación es escribir `npx --package=<paquete>@<versión>` como comando del servidor y darlo por resuelto: es una línea de texto y no descarga nada en la instalación. Precisamente por eso no sirve. **`npx` no es un paso de instalación: es un paso de arranque.** El paquete se resuelve la primera vez que el CLI anfitrión spawnea el servidor, y vuelve a consultarse en cada arranque posterior.

Medido con una versión exacta y una caché de npm dedicada: con la caché fría, el primer arranque tarda nueve segundos y deja setenta y dos megabytes. Con la caché caliente arranca en poco más de un segundo. Pero con la caché caliente, la versión exacta ya resuelta y el registry inalcanzable, **`npx` se cuelga un minuto y medio y después falla**. La caché no lo vuelve autosuficiente; solo el modo offline explícito lo hace, y ese modo depende de una caché que no es nuestra y que el usuario puede borrar con una orden.

Un MCP que necesita la red para arrancar traslada el riesgo desde la instalación —donde hay una persona mirando, un reporte y un rollback— hasta el arranque del agente, que es el peor lugar posible para descubrirlo. Por eso el paquete se materializa en instalación y la configuración apunta al binario resuelto por ruta absoluta.

#### Dónde vive Pegasus

Pegasus ya tiene un lugar propio: la unidad 2 dejó el journal en `~/.local/share/pegasus-harness/`, un directorio que crea con permisos `0700`. Lo que esa ruta no tiene es un resolutor — está escrita a mano y no consulta el entorno, así que hoy es una convención de Linux disfrazada de camino universal. Esta unidad le pone el resolutor que le falta, porque es la primera que necesita poner ahí algo que no es estado propio, y la unidad 4 lo adopta cuando llegue.

El directorio pasa a respetar la convención de cada plataforma: `$XDG_DATA_HOME/pegasus-harness/` con fallback a `~/.local/share/pegasus-harness/`, `~/Library/Application Support/pegasus-harness/` en macOS, `%LOCALAPPDATA%\pegasus-harness\` en Windows. El journal se muda con él: hay un solo lugar donde vive Pegasus, no uno para su estado y otro para lo que baja. No hay estado que migrar —v4 no está publicado— y el journal de v3 queda aún más lejos de lo que ya estaba, que es exactamente donde debe estar.

Las dependencias cuelgan de `deps/<id>/<versión>/`, con la versión en la ruta: actualizar es colocar al lado y retirar lo viejo, que es exactamente la forma que el motor de la unidad 7 ya sabe ejecutar.

Falta una pieza del núcleo para que eso sea posible. Hoy el catálogo y el registry rechazan cualquier artefacto cuya ruta caiga fuera del directorio de configuración del CLI anfitrión, y tienen razón: un adapter que escribe fuera del territorio de su CLI es un error. Pero el directorio propio de Pegasus es un segundo territorio legítimo, y los dos gates tienen que aprender a distinguirlo de una fuga. Mientras no lo hagan, lo que se baja no puede colocarse por el camino normal.

**Lo que baja es un artefacto nuestro como cualquier otro**: entra al journal, tiene digest, se le detecta la mutación y se retira con rollback. Escribirlo en un directorio compartido del sistema sería reclamar una dirección que no es nuestra, y el planner tendría razón en negarse: si el usuario ya tiene ese binario instalado por su cuenta, pisarlo es justo lo que la unidad 7 se construyó para no hacer.

#### La plataforma no soportada se rechaza

Si el par SO/arch que corre no está entre los que el descriptor declara, la instalación se rechaza y lo dice. No hay tabla de degradaciones ni instalación parcial silenciosa: una instalación a medias es peor que una que no ocurrió, porque miente sobre lo que dejó.

#### El usuario elige, y el contenido se adapta por ausencia

Cuáles MCPs se instalan lo decide el usuario. La paridad que el resto del producto exige se sostiene sin construir la TUI acá, porque **la selección no vive en ninguna superficie**: es una función pura del núcleo que recibe el contenido y los ids elegidos y devuelve el contenido que sobrevivió. Las flags la llaman en esta unidad; la TUI de la unidad 5 la llamará igual, sin agregarle nada.

Que la selección se aplique una sola vez, en el núcleo y antes de renderizar, no es una comodidad: un adapter renderiza un ítem a la vez y nunca ve el árbol completo, así que un render por ítem no podría saber qué eligió el usuario ni aunque quisiera. Aplicarla una vez es lo que deja a todos los adapters —y a cualquier superficie futura— sin enterarse de que hubo una elección.

**Una herramienta que llega con un MCP no puede ser un requisito.** Si el usuario elige qué servidores se instalan, declarar una de sus herramientas como requerida nombra una condición que algunas instalaciones no pueden cumplir nunca. Esas herramientas van entre las opcionales, donde declinar el servidor significa simplemente que la herramienta no se concede, en vez de dejar una promesa incumplible. Hoy el motor todavía no sabe qué herramientas provee cada MCP, así que la regla se sostiene con un test; la categoría `mcp/` es lo que va a permitir que el loader la rechace de plano, y ahí el test pasa a ser innecesario.

Un MCP que no se seleccionó no puede quedar mencionado como si estuviera. Eso se resuelve sin condicionales en la prosa, por dos vías. **`optional_tools` pasa a significar algo**: hoy el render lo fusiona con `requires_tools` y concede ambos por igual, así que la distinción no cambia nada; a partir de esta unidad una herramienta opcional se concede solo si su MCP viaja. Y **el cuerpo del descriptor de cada MCP es su convención**, así que si el MCP no se selecciona su convención tampoco se embarca: es el mismo artefacto, no dos que hay que mantener sincronizados.

La prosa de las convenciones ya está escrita defensiva —dice qué hacer cuando la referencia no está, en vez de asumirla— y la que todavía no lo esté se pasa a esa forma. Es más barato que sostener contenido condicional, y no le pide a la revisión adversarial que juzgue prosa con ramas, que es donde fabrica contradicciones.

Que el cuerpo del descriptor sea la convención tiene una consecuencia que conviene decir antes de que sorprenda: **hoy no todas las convenciones están donde van a vivir.** La de memoria viaja inlineada en el prompt de sistema, que es el único artefacto que se embarca en toda instalación pase lo que pase. Hoy abre diciendo cuándo aplica, así que no engaña a nadie; pero un usuario que no seleccionó ese MCP recibe igual el protocolo entero y tiene que leerlo para descubrir que no le toca. Esta unidad la muda al descriptor, que es donde la selección puede alcanzarla.

Y en la dirección opuesta hay un MCP sin una sola línea de prosa en todo el contenido. Instalarlo así sería pagar una capacidad que ningún agente sabe que existe: no rompe nada, simplemente no sirve para nada. Su convención se escribe en esta unidad, en el cuerpo de su descriptor, junto con el mecanismo.

#### Un agente declara servidores, no las herramientas que traen

`optional_tools` significaba dos cosas a la vez: herramientas nativas del CLI y herramientas que sólo existen porque un servidor está instalado. `sdd-explore` lo mostraba en una sola línea —`optional_tools: [write, codebase-memory]`— donde `write` es nativa y la otra llega con un MCP. Un campo, dos conceptos, y ninguna regla que pudiera distinguirlos sin adivinar.

Se separan. `requires_tools` y `optional_tools` nombran **sólo herramientas nativas**; `optional_mcp` nombra **ids de servidor**, y desde la inversión de la declaración ya no lo escribe el agente: lo deriva el cargador de las listas `reaches` de los descriptores (ver `Deudas resueltas`). Y no hay `requires_mcp`: un servidor que el usuario puede declinar no puede ser un requisito, y ahora eso es estructural en vez de una regla sostenida por un test — no hay campo donde escribirlo.

Tres cosas se caen solas con la separación:

- **El permiso deja de ser una tabla y pasa a derivarse.** El adapter escribe cada servidor en `/mcp/<id>`, así que el id *es* la clave que el CLI usa para nombrar sus herramientas, y el patrón de permiso es esa misma clave con el comodín. La tabla de traducción del adapter vuelve a nombrar sólo herramientas nativas.
- **El descriptor no declara qué herramientas provee.** Nadie lo leería: el agente nombra el servidor y el permiso sale del id. Un campo sin lector es documentación que se desincroniza en silencio.
- **Un id que ningún descriptor provee es un error de carga**, no una herramienta que se deja de conceder sin que nadie avise.

#### Invariantes en los dos bordes

La misma idea aplicada dos veces, en los dos lugares donde una tabla tiene que cubrir un enum: el catálogo verifica al importar que toda capacidad no interactiva tenga fuente, y el adapter verifica al importar que toda forma de distribución tenga traducción. Los dos con `if` y `raise`, no con `assert`: `python -O` borra los `assert`, y un invariante que desaparece bajo optimización desaparece exactamente en producción.

Sin el segundo, agregar `npm` al núcleo en 8b habría renderizado un servidor npm como si fuera remoto, en silencio. Con él, no se puede ni importar el módulo hasta que el adapter sepa qué hacer.

#### La convención aterriza donde ya viven las convenciones

El cuerpo del descriptor se escribe en `_shared/mcp/<id>-convention.md`, que cuelga del mismo `_shared/` donde viven las convenciones escritas a mano y donde el contenido embarcado las referencia por su ruta. Sin placeholder nuevo, sin ancla de layout nueva.

El subdirectorio propio no es cosmético. `_shared/` tiene convenciones escritas a mano, y un id de servidor puede coincidir con el nombre de una de ellas. Si la convención de un servidor cayera en el mismo espacio de nombres plano, un id que coincidiera con uno de esos stems pisaría un archivo con el que no tiene nada que ver. `mcp/` como subdirectorio propio no detecta esa colisión al construir el catálogo: la vuelve imposible de escribir.

Eso resuelve el alcance sin condicionales en la prosa y sin conocimiento cruzado. **La referencia es siempre la misma frase; lo condicional es el archivo.** Si el servidor no se eligió, el archivo no se escribe, la cláusula defensiva se activa, y ningún agente leyó una convención que no le tocaba. La alternativa —enlazar la convención globalmente, como hace el prompt de sistema— se descartó: le habría mandado la convención de cada servidor a los doce agentes, que es el mismo defecto que esta unidad viene a corregir.

#### Los dos tests que esta unidad volteó

Dos tests afirmaban la ausencia de MCP, y los dos eran correctos: describían el estado real. Se volvieron rojos como primer paso de 8a1 y el código los puso en verde. Lo que sigue es por qué el segundo no podía simplemente actualizarse.

El primero afirma que el adapter de OpenCode no declara la capacidad y no implementa su render. Voltearlo es exactamente el trabajo de 8a1, y no tiene más vuelta.

El segundo esconde un problema que la unidad tiene que resolver, no heredar. Afirma que el catálogo rechaza una capacidad declarada sin fuente de contenido, y para eso necesita una capacidad que no tenga fuente. Hoy hay una sola: `mcp`. La única otra capacidad sin entrada en la tabla de fuentes es la de modelo por agente, que está clasificada como interactiva y por eso nunca llega a la consulta. **En cuanto esta unidad le dé fuente a `mcp`, ese test se queda sin sujeto posible**, y la rama que lanza el error queda inalcanzable: código muerto con un test que ya no puede ejercitarlo.

La salida no es buscarle un sujeto nuevo, es que la condición no pueda existir. La tabla de fuentes queda obligada a cubrir toda capacidad no interactiva, y esa obligación se verifica una sola vez al cargar el módulo. La consulta pasa a ser directa, sin rama de error, y el test pasa a afirmar la cobertura de la tabla en vez de un rechazo: no necesita sujeto, no puede quedarse sin él, y falla al importar si alguien agrega una capacidad y se olvida de su fuente. El error deja de poder ocurrir en la instalación de un usuario y pasa a ocurrir en la máquina de quien lo escribió mal.

#### El corte de la unidad

La unidad completa se pasa del presupuesto de revisión, así que va en cadena:

- **8a1.** La categoría `mcp/` y su loader, el descriptor, la entrada de la capacidad en el catálogo, el render del servidor y de su convención, y el flip de la capacidad en el manifiesto del adapter. Entra la forma `remote`. Al terminar, hay un MCP realmente instalado, con su convención embarcada y su permiso concedido a los agentes que lo declaran.
- **8a2.** La selección: `--mcp` decide qué servidores se instalan, y dejar de nombrar uno que ya estaba instalado lo retira.
- **8b.** El directorio propio de Pegasus, el puerto que materializa y verifica, y las formas `npm` y `download` sobre él. **Medida: entre 2300 y 4100 líneas**, así que va en cadena de cinco, y el orden no es de comodidad. El resolutor va primero porque la unidad 4 está bloqueada en él y porque todo lo demás necesita un lugar estable donde materializar. El journal va antes que el buscador porque es el único PR que toca un esquema sin ruta de migración y merece revisarse solo. `download` va antes que `npm` por ser el mecanismo más simple —bajar, verificar, extraer— y entrega una forma completa antes de abrir la más compleja. El borrado de los dos gates defensivos viaja en el último, porque sacarlos antes de que existan los descriptores que los vuelven innecesarios dejaría una ventana con la convención embarcada y sin guarda.

**Node es precondición de instalación, no algo que Pegasus materialice.** La forma `npm` se resuelve con `npm ci --ignore-scripts` contra un lockfile fijado, y eso exige un Node en el PATH del usuario. Pegasus lo verifica y lo dice cuando falta; no lo instala. Instalar un runtime completo es otra unidad y otro problema de seguridad, y meterlo acá haría que la unidad que distribuye MCPs además distribuya lenguajes.

**Lo que la medición encontró y hay que arreglar en 8b3.** `retire` no recorre entradas: las parte en dos listas fijas, `kind == "file"` y `kind == "config-key"`. Una dependencia materializada no cae en ninguna, así que no se borraría **ni se reportaría** — ni siquiera como `unaccounted`. Un `uninstall` dejaría el binario en el disco y diría que limpió todo. Y `retire` sólo llama `remove`, que es de archivos: un árbol materializado necesita `remove_dir`.

8a se midió al escribir su código y se pasó del presupuesto, así que se partió en dos. La costura no es arbitraria: 8a1 instala el servidor para todos, 8a2 le da al usuario la decisión. Cada mitad deja el árbol coherente, y ninguna embarca una capacidad que no funcione.

#### El retiro salió más grande que su fila

8a2 se escribió para que dejar de nombrar un servidor MCP lo retire, y lo que quedó construido no sabe qué es un MCP. La pregunta que faltaba era general —*el journal reclama esto y el render ya no lo produce*— y su respuesta también: `planner.retirements(installed, artifacts)` es una diferencia de conjuntos sobre ids, y `Plan` la expone como una colección de `Record`s.

Que sea de `Record`s y no de `Step`s no es un detalle de implementación. Un `Step` lleva un artefacto, y un retiro se define justamente por que el render no produjo ninguno: lo único que queda de él es lo que el journal todavía recuerda. Forzar las dos cosas a una misma forma sería mentir sobre el dominio, y el núcleo ya admitía esa asimetría en otro lado —`Retired` es un tipo aparte de `Applied` por la misma razón.

La regla vive en el núcleo y no en `cli.py` por una sola razón, y no es la comodidad de que el `--dry-run` la reporte gratis: `tui/` va a ser el segundo adapter conductor, y el punto de un hexágono es que todos obtengan la misma respuesta del núcleo. Duplicar un cálculo es barato; duplicar una regla del contrato de propiedad hace que la CLI y la TUI diverjan en el criterio, no en el número.

La consecuencia que importa para lo que viene: **el día que una release deje de embarcar una skill, un comando o un agente, esto lo retira**. Los MCPs fueron el primer llamador, no el único.

Dos cosas quedaron atadas al retiro y no son negociables. El snapshot cubre las direcciones retiradas —la ruta de un retiro nunca cae en `plan.placements`, así que sin nombrarla el `restore` devolvería la clave de un servidor y no su archivo de convención—; y el journal descarta **lo que `retire` confirmó haber removido**, nunca lo que se pretendía remover, porque una entrada que quedó `unaccounted` sigue en disco y perder su registro la orfanaría para siempre.

#### Lo que el dry-run no puede prometer

`--dry-run` anuncia los retiros, y para un artefacto con dirección propia lo que anuncia es lo que va a pasar. Para un ítem agregado a una lista —puntero terminado en `/-`— puede quedarse corto: si el usuario lo editó más allá de reconocerlo, la corrida real lo va a dejar `unaccounted` en vez de removerlo, y el dry-run no tiene cómo saberlo.

No es un defecto a arreglar, es el precio de dos decisiones deliberadas: `retirements()` es pura y no mira disco, y el dry-run no llama a `retire`. Comprar la precisión exigiría romper las dos.

Esta unidad es la que destraba la deuda del caso wildcard contra wildcard del deny de herramientas: hasta que haya un MCP instalado no hay ningún prefijo que habilitar, y el caso no se puede verificar en runtime.

**Nada de esto se porta de v3.** El contrato de release de v3 sirve como inventario de qué datos hicieron falta alguna vez, no como plantilla: aquel diseño compilaba el binario a mano dentro de una imagen fijada por digest, lo vendorizaba en el repositorio y terminaba admitiendo en su propio archivo de provenance que la firma no se podía verificar. Los campos del descriptor se diseñan de cero contra los tres mecanismos de arriba.

### Unidad 9 — El digest deja de ser permiso: instalar y desinstalar pisan, el snapshot recupera

Hoy el digest cumple dos papeles a la vez: es lo que decide si un artefacto se pisa, y es lo que decide si se puede recuperar. Esta unidad los separa. La política pasa a ser tres reglas:

- **Instalar** escribe todo lo que el journal reclama, sin mirar si el usuario lo tocó. Lo que el journal no reclama —el caso C— sólo se escribe con confirmación explícita.
- **Desinstalar** borra todo lo que el journal reclama, sin mirar si el usuario lo tocó.
- **Recuperar** es el snapshot y `restore`. No el journal.

El digest deja de ser una condición que el planner consulta antes de escribir. La pregunta "¿esto es lo que dejamos la vez pasada?" se borra del camino de instalar y de desinstalar, y la única pregunta que sigue viva es "¿esto es nuestro?", que contesta el journal solo.

Conviene decir primero qué NO justifica el snapshot, porque los dos argumentos obvios están mal. El caso C —una dirección que el journal no reclama y que la instalación quiere ocupar— ya está protegido: se pide confirmación explícita, y el snapshot no le agrega nada, porque ahí nunca se escribe sin que alguien mire. Y una instalación que se corta a mitad de camino ya está protegida por el rollback en memoria que hoy vive en el planner (`Applied.replaced` y `_put_back`, `planner.py`): ese mecanismo deshace lo que un solo comando alcanzó a tocar, mientras el comando está corriendo.

El hueco real es uno solo: **una dirección que el journal sí reclama, donde el usuario editó a mano el archivo que es nuestro.** Ahí la política nueva escribe sin preguntar —es la primera regla de la lista—, así que no hay consentimiento y no hay aviso. El snapshot existe para que ese contenido no desaparezca sin dejar rastro en ningún otro lado. El precio se dice en voz alta: si pasaron más instalaciones que las que la retención guarda, el contenido original no existe en ningún lado.

#### Lo que murió, y la lección que dejó

El inventario de símbolos borrados vivía acá y se retiró: una vez que un símbolo no existe, listarlo no ayuda a nadie —no se puede ir a mirar— y la lista sólo envejece. Lo que sí vale la pena conservar es por qué el borrado salió barato.

**`with_mutation` y `with_adoption` nunca tuvieron un llamador de producción.** Sus únicos call sites eran los tests unitarios del propio journal. El motor que se distribuye jamás produjo una mutación ni un registro adoptado, porque el comando que la produciría —`models set`— todavía no existe. Se borró un mecanismo completo, probado y serializado, que no tenía un solo usuario.

Eso deja una pregunta que conviene hacerse antes de construir, no después: **si esto se puede borrar sin que nadie lo note, ¿por qué estaba?** La respuesta fue que se construyó para una superficie —la asignación de modelos— que se diseñó antes y se sigue posponiendo. Un mecanismo sin llamador es una apuesta a que el llamador va a llegar, y acá la apuesta se perdió por dos unidades enteras.

#### Lo que sobrevive, y no por razones de política

`unaccounted` sobrevive: un ítem de una lista no tiene dirección propia, así que "el usuario lo borró" y "el usuario lo editó hasta volverlo irreconocible" son físicamente indistinguibles, y esto sólo aplica a listas que todavía tienen sobrevivientes. El digest sobrevive como identificador de esos ítems y como dato de `doctor`. `ownership.occupies` sobrevive porque es exactamente la detección del caso C. `retire` y `unplace` sobreviven en su estructura actual. `cli._merged` sobrevive. Y `Capability.PER_AGENT_MODEL` sigue clasificada `INTERACTIVE` en `catalog.py`: esta unidad no la reclasifica.

#### Asignación de modelo — lo que esta unidad hace y lo que no

El diseño actual asigna modelos registrando una mutación sobre nuestro propio artefacto: `journal.py` tiene hardcodeado el literal `"set-model-adopted"` en `_amend`. Ese mecanismo muere acá. El reemplazo —que se construye con el menú interactivo, no en esta unidad— se resume en un principio:

> Una asignación de modelo no es una mutación de nuestro artefacto. Es una preferencia que vive en el estado propio de Pegasus y participa del render.

Dos consecuencias quedan registradas para cuando llegue esa unidad. Pisar el artefacto pasa a ser inofensivo, porque la asignación deja de vivir en el artefacto: es parte de lo que renderizamos, no algo que hay que proteger de nuestra propia escritura. Y la preferencia va a vivir en su propio store, con su propio puerto, al lado del journal pero con una postura de falla opuesta: **falla blando**. Ausente o ilegible degrada a "sin asignación" y se renderiza el default, deliberadamente al revés que el journal, que revienta ante un archivo corrupto porque degradar ahí orfanaría artefactos propios. Esta unidad sólo borra y documenta el principio; no construye ese store.

#### El snapshot — el contrato de diseño

El snapshot captura el archivo entero, siempre. Un blob por archivo tocado, sin importar si Pegasus iba a escribir el archivo completo o sólo una clave adentro. `restore` devuelve bytes exactos y modo exacto, sin merge ni reconstrucción — el modo importa porque `_write_document`, en `planner.py`, ya escribe un documento de configuración con el modo que el archivo tenía antes, y devolverlo como `0644` rompería algo que el motor ya respeta hoy.

El snapshot captura también el journal. El journal no está en `plan.placements` —lo guarda el store propio, no el planner—, así que hay que agregarlo a mano a lo que se captura. Si no, `restore` devuelve los archivos al estado anterior mientras el journal sigue reclamando la versión nueva, y la próxima instalación compara contra las huellas equivocadas.

Es una carpeta por generación, numerada con un número creciente, colgando del mismo directorio donde vive el journal:

```
~/.local/share/pegasus-harness/snapshots/
  000004/
    manifest.json
    0001.blob
```

El manifest se escribe último, como marca de que la generación está completa. Una carpeta sin manifest la ignoran tanto `restore` como la retención. Cada entrada del manifest tiene la ruta, `existed`, el modo, y la referencia al blob. `existed: false` significa que ahí no había archivo, así que volver a ese estado es borrar la ruta — eso es lo que permite que `restore` devuelva el estado anterior exacto y no simplemente sobrescriba.

La fecha va adentro del manifest, no en el nombre de la carpeta. La razón real: en los tests el reloj es un literal fijo (`AT`, en `tests/test_cli.py`), y el test que prueba "hay snapshot en instalar Y en desinstalar" toma exactamente dos snapshots en una misma corrida — con la fecha en el nombre, colisionarían. Una razón secundaria: `timespec="seconds"` no da orden total, y la retención necesita ordenar. No vale el argumento de que en producción dos snapshots en el mismo segundo son improbables — ese argumento se consideró y se descartó.

`restore` deshace la instalación completa, no un rescate selectivo archivo por archivo. Devuelve todo lo que la instalación tocó, y hay que decirlo sin vueltas: eso significa que también se vuelve a la versión anterior de todo lo demás que esa instalación actualizó, no sólo del archivo que motivó la recuperación.

La retención guarda 20 generaciones, y no es un argumento de disco: el contenido son 80 archivos y 356 KB, el catálogo renderiza 89 archivos y 23 claves de configuración, así que un snapshot de reinstalación son unos 400 KB y veinte generaciones son unos 8 MB -- medido en una máquina real, cinco generaciones ocupan 436 KB en total (64-144 KB cada una), muy por debajo de esa cota superior, porque una instalación real toca menos archivos que el peor caso de reinstalación completa. Lo que la retención decide en realidad es cuánto atrás llega la promesa de recuperación.

El puerto de filesystem crece dos métodos: `list_dir` —para calcular el próximo número de generación y para la retención— y uno para borrar un directorio, que sólo usa la retención. Hace falta porque `remove` es explícitamente sólo para archivos (`ports/filesystem.py`; en `fs_posix.py` es `path.unlink`, que falla contra un directorio). No hay archivos comprimidos en ningún lado de `src/`: los snapshots son archivos sueltos, por diseño.

#### El corte — cuatro PRs, con la medición

Medido: mueren 119 líneas de fuente (journal.py 65, planner.py 37, ownership.py 9, cli.py 3, registry.py 1, ports/cli_adapter.py 4); mueren 29 tests y se editan 6; cero tests se invierten; quedan 543 de 572; y 73 líneas de documentación en doce ubicaciones, de las cuales 51 son borrado limpio.

Estimado: ~374 líneas de fuente nueva, ~705 de tests, ~70 de prosa. Las estimaciones se dimensionan contra varas ya medidas en el repo: `ports/journal_store.py` con 47 líneas, `infra/journal_store_file.py` con 104, y la proporción test-sobre-fuente que el propio repo ya tiene, 2,5×, tomada de `tests/test_journal_store.py` con 264 líneas.

| PR | Contenido | src | tests | doc | Total |
|---|-----------|-----|-------|-----|-------|
| 1 | Manifest, store y puerto, más `list_dir`. Nada lo llama todavía: cero cambio de comportamiento | 187 | 210 | 0 | 397 |
| 2 | Escritor de snapshot y su cableado en install y uninstall. Desde acá no se escribe sin red | 102 | 275 | 50 | 427 |
| 3 | Muere la política vieja: la tabla completa, los 29 tests, las doce ubicaciones de documentación | 119 | 161 | 63 | 343 |
| 4 | `restore`, retención, y el método para borrar un directorio | 127 | 255 | 20 | 402 |

Dos cosas hacen que el corte sea éste y no otro. **PR 2 tiene que entrar antes que PR 3**, y no es prolijidad: borrar la maquinaria vieja de preservar/restaurar mientras instalar todavía puede escribir sin snapshot abre una ventana donde una edición del usuario se destruye sin ninguna red — peor que el comportamiento de hoy, no un intermedio aceptable. Y el corte en dos que se consideró primero —política más escritura del snapshot en un PR, restore más retención en el otro— se descartó con números: su primer PR daba cerca de 1145 líneas, y sólo la mitad de nacimiento (802) ya pasaba el presupuesto de 800 líneas antes de sumarle una sola línea de muerte.

Queda registrado que las estimaciones se remiden cuando cierre el PR 1: los PRs 2, 3 y 4 se recalibran contra líneas reales en vez de contra la analogía de arriba.

---

### Unidad 10 — El puerto de filesystem puede decir "no puedo saberlo"

El puerto declara, en `ports/filesystem.py`, que `exists` responde *"Whether anything is at this path. Never raises."* La implementación POSIX es `return path.exists()` sin `try/except`, y es el único de los diez métodos de la clase que no envuelve `OSError`. `Path.exists()` sólo se traga los errores que ya significan ausencia; un padre que no se puede atravesar levanta `EACCES`. Verificado corriendo, en Python 3.12.3: un directorio en modo 000 le da al usuario un traceback crudo desde cualquier comando, no un reporte.

Eso es el síntoma. El problema es más abajo.

#### El arreglo obvio destruye datos, y está medido

La corrección evidente es tragarse el `OSError` y devolver `False`, que es lo que el contrato declarado pide y lo que dos métodos vecinos ya hacen. Se escribió, con su test, y se midió contra disco real antes de shippearla:

```
snapshot de la generación 2, tomado con un directorio en modo 000
  entradas totales:        17
  anotadas como AUSENTES:  16     ← los 16 archivos existen

restore de esa generación, con los permisos ya arreglados
  generation 2: wrote back 1, removed 16.
  exit=0

archivos en el directorio después:  0
```

**`restore` borró dieciséis archivos que existían y reportó éxito.** El estado de hoy, con el traceback, no pierde nada: revienta antes de guardar el snapshot, así que no llega a crearse una generación mentirosa. Lo de hoy es feo y seguro; el arreglo mínimo es prolijo y peligroso. La rama se borró sin pushear.

#### La causa: un bool para dos preguntas

`exists` devuelve `False` tanto para *no hay nada* como para *no puedo saberlo*, y hay sitios donde esa distinción es la que decide qué se borra. El peor no es el snapshot.

`planner._file_step` **ya tiene** la guarda contra exactamente esta pérdida de datos. Su docstring la nombra: *"a file that cannot be read is a file that cannot be copied, and writing it would destroy the only version there is with nothing left to give back"*, y la implementa en el `except FileSystemError` del `read_bytes`. Pero el `if not filesystem.exists(...)` está cinco líneas más arriba y **la rodea**: devuelve `CREATE`, y `apply` sobreescribe. El arreglo obvio no abriría un agujero nuevo, desactivaría una protección escrita a propósito.

Y `FileJournalStore.load` hace `if not exists(): return empty()`. Un journal ilegible se convierte en un journal vacío, y todo lo que sigue procede como si Pegasus nunca hubiera instalado nada. `ensure_writable`, que corre antes, sólo chequea privilegios y no toca disco, así que no lo atrapa.

#### No es un método, es un patrón

Cuatro métodos disfrazan "no puedo saberlo" de una respuesta benigna. Cinco —`read_bytes`, `write_atomic`, `remove`, `remove_dir`, `make_dir`— están bien y sirven de vara.

| Método | Lo que declara el puerto | Lo que hace |
|--------|--------------------------|-------------|
| `exists` | "Never raises" | levanta `EACCES` |
| `mode_of` | "o `None` cuando está ausente" | se traga cualquier `OSError`, sin declararlo |
| `owned_by_current_user` | "`False` cuando no existe" | se traga cualquier `OSError`, sin declararlo |
| `list_dir` | "una ruta que no existe lista vacío" | hereda el `path.exists()` crudo: un directorio ilegible lista `[]` |

De los cuatro, **esta unidad arregla `exists` y `list_dir`**. `list_dir` entra porque ya es uno de los trece sitios auditados y su arreglo está contado en la implementación; los otros dos se van a la unidad 11, porque hacen cosas distintas con "no puedo saberlo" y una de ellas ya está bien.

#### Los trece sitios, auditados

Once llamadas a través del puerto más dos dentro de la propia implementación. La clasificación es por lo que causaría un `False` que en realidad significa "no puedo saberlo":

| Consecuencia | Sitios |
|---|---|
| **Destructiva** — se pierden datos | `planner._file_step` (planifica `CREATE` sobre un archivo que existe, y `apply` lo pisa); `planner._read_document`; `FileJournalStore.load`; `capture_paths` |
| **Deshonesta** — un reporte o el journal afirma algo falso | `retire` (saltea el borrado y apila el id en `removed` igual); `_current_digest` (`doctor` reporta como ausente algo presente); `readable_generations` (un `restore` sin argumento elige una generación más vieja que la última); y los tres `left`/`existing` de `_install` |
| **Benigna** — degrada sin daño | `FileSnapshotStore.read` (rechaza igual, con el motivo equivocado); `list_dir` |

#### Lo que construyó, y lo que costó

`exists` levanta `FileSystemError` cuando no puede responder, y sigue devolviendo un `bool` para presente y ausente. Se eligió contra la alternativa de tres estados con la medición adelante: ~173 líneas contra ~323, porque la propagación ya estaba cableada en el `except` de `main` y ocho de los trece sitios no necesitaron un solo cambio. Y porque `None` es *falsy* en Python: un tercer estado habría reintroducido este mismo defecto, en silencio, en cualquier `if fs.exists(path):` escrito después.

Tres sitios necesitaron trabajo, y en los tres la propagación pelada era peor que el bug. `doctor` ganó un tercer balde —una entrada que un permiso tapa no está ausente ni derivada— porque sin eso una sola entrada ilegible se habría llevado el reporte entero. `readable_generations` pasó de comprehension a bucle explícito, porque una generación vieja ilegible habría abortado encontrar cualquiera, incluida la más nueva y buena. Y las dos consultas de `left_behind`, que corren adentro de un handler que ya está reportando otra falla, dejaron de poder reemplazar ese mensaje específico por el genérico.

El alcance quedó en `exists` y `list_dir`. `mode_of` y `owned_by_current_user` comparten la forma del defecto y hacen cosas distintas con él —uno falla cerrado y ya está bien—, así que se fueron a la unidad 11.

**La estimación se pasó 195%**: ~173 líneas estimadas, 511 reales. Es el tercer caso del mismo patrón —la unidad 9 se pasó 130% en su PR de infraestructura, y la primera medición de esta unidad 128%—, y ya no es anécdota: **cuando una unidad crea cañería nueva, la estimación es un piso y no un número.** Parte del sobrecosto fue construir infraestructura del doble de test, que la migración a filesystem real elimina.

#### El piloto de disco real, y el defecto que encontró

La primera tarea fue el doble y no el puerto: `FakeFileSystem` tenía seis hooks de falla y ninguno para `exists`, así que el escenario era literalmente inconstruible y no había forma de escribir un test en rojo.

Pero enseñarle al doble fue el último hook que se le agregó, no el primero de una serie. Dos tests pasaron a correr contra un home descartable con el filesystem real, produciendo las condiciones en vez de inyectarlas: un directorio que de verdad no se puede escribir, y la falla de consulta atada al **estado del disco** —falla una vez que el archivo existe, porque `apply` lo crea entre las dos consultas— en lugar de a un contador de llamadas.

Salieron rojos, y encontraron un defecto que el doble escondía: `unplace` también consulta el filesystem, y esa llamada no estaba guardada, así que la excepción se escapaba del handler igual. El test anterior pasaba porque su contador caía en la consulta de al lado. **Un número de llamadas codifica cuántas veces el motor pregunta hoy**: se agrega una consulta en cualquier parte y el test queda verde verificando otra cosa.

Un test se borró en vez de migrarse. Nada cambia en el disco entre la consulta de `existing` y la que `plan` ya hizo sobre los mismos documentos, así que ninguna condición real hace fallar una y no la otra, y las dos se niegan antes de colocar un artefacto. Probar ese sitio por separado exigía contar llamadas. La garantía quedó cubierta por los casos `fail_exists` de `test_planner`.

De acá sale la decisión de migrar los tests a filesystem real sobre home descartable, y la clase base que esa migración va a reusar.

#### Por qué va antes de 8b

8b materializa dependencias en el directorio propio de Pegasus y las mete al journal como artefactos. Es la unidad que más superficie de archivo nueva agrega, y toda esa superficie pasa por los mismos trece sitios. Arreglar el puerto después significaría auditarla dos veces.

---

### Unidad 11 — `mode_of` y `owned_by_current_user` — esbozo, sin contrato todavía

**Esta unidad está esbozada, no medida.** Lo que sigue es lo que se sabe hoy y el punto de partida de su auditoría; el contrato se escribe cuando esa auditoría exista, igual que la 10 esperó a tener sus trece sitios clasificados.

`mode_of` y `owned_by_current_user` comparten con `exists` la forma del defecto —se tragan cualquier `OSError` y devuelven un valor benigno, sin que su docstring en el puerto lo declare— y por eso la tentación es arreglar los tres juntos. **Es la decisión equivocada, y no por prolijidad de proceso: los tres hacen cosas distintas con "no puedo saberlo", y una de ellas ya está bien.**

#### Los tres comportamientos, que son tres y no uno

**`owned_by_current_user` falla seguro, y no hay que tocarlo como a los otros.** Sus dos llamadores son el mismo guard, en `infra/journal_store_file.py` y en `infra/snapshot_store_file.py`:

```python
if not self._fs.owned_by_current_user(self._home):
    raise JournalStoreError(f"{self._home} belongs to another user; refusing to write its journal")
```

Un "no puedo saberlo" da `False` y **se niega a escribir**. El error empuja hacia el lado seguro. Aplicarle el diseño de la unidad 10 —que levante— convertiría un guard que hoy falla cerrado en un crash: sería empeorarlo. Lo que probablemente necesita no es cambiar de comportamiento sino que su docstring diga la verdad sobre por qué devuelve `False`.

**`mode_of` va para el otro lado, y su default merece una aclaración que costó caro.** En `core/planner.py`, dentro de `_put_back`, el rollback escribía así:

```python
filesystem.write_atomic(path, content, mode=mode if mode is not None else 0o644)
```

El `None` que llega de `mode_of` puede significar "la ruta no existe" o "no pude leer sus bits", y las dos colapsaban en `0o644`. Leído así parece una pérdida de confidencialidad: un archivo del usuario en `0600` que el rollback deja legible por todos.

*(Las dos mitades de esto se cerraron después, y el código citado arriba ya no está en el árbol: `_write_back` omite el argumento en vez de elegir un default que no le toca, y `mode_of` distingue las dos condiciones en el puerto. Ver "Deudas resueltas". Se conserva el planteo original porque la lección que sigue abajo es la que vale.)*

**No lo es, y verificarlo importó.** En `_undo`, un archivo que no existía llega con el contenido en `None` y el código toma la otra rama: **borra, no escribe**. Y donde sí escribe, `mode_of` corre justo después de un `read_bytes` que ya tuvo éxito, así que para que devuelva `None` habría que no poder consultar los permisos de un archivo que se acaba de leer. El único sitio que llega con `None` de verdad es `_write_document` creando un documento que todavía no existe, y ahí `0o644` es el default correcto.

Queda entonces como **fragilidad latente**, no como defecto vivo: si alguien reordena esas dos llamadas o agrega un llamador nuevo, se vuelve alcanzable. La unidad no se justifica por esto sino por el octal dentro del núcleo.

Y queda la regla que salió de habernos equivocado acá: **un defecto no se afirma sin reproducirlo.** Los dieciséis archivos de la unidad 10 se corrieron y se midieron; esto se afirmó leyendo, y estuvo mal.

Queda abierto si lo que hay que arreglar es el método, el `else 0o644` de `_put_back`, o los dos. Son archivos distintos, y la respuesta sale de la auditoría, no de antes.

**Y hay un tercer comportamiento en `infra/snapshot_store_file.py`**, donde un `mode` en `None` sobre una ruta que sí existe choca con la validación de `core/snapshot.py` —*"an entry that existed needs both a mode and a blob reference"*— y levanta `SnapshotError`. Ruidoso pero seguro: ni silencioso como el rollback, ni cerrado como el guard.

#### Con qué arranca la auditoría

Ocho llamadores, ninguno clasificado todavía. `mode_of`: `planner.py` (decide `UNCHANGED` contra `UPDATE`), `planner.py` y `planner.py` (la captura para el rollback), `planner.py` (preservar el modo al reescribir un documento en `retire`), y `snapshot_store_file.py`. `owned_by_current_user`: los dos guards ya citados.

Hay una pista que la auditoría debería confirmar o descartar temprano: en varios de esos sitios `mode_of` corre **inmediatamente después de un `read_bytes` que ya tuvo éxito**, así que la ventana en la que el `stat` falla y la lectura no es estrecha. Si eso se sostiene en los seis, la unidad es más chica de lo que parece; si no, es más grande. Medirlo es la primera tarea, antes de estimar una sola línea.

#### Por qué no entra en la unidad 10

La clasificación de la unidad 10 responde una pregunta —qué causa un `False` de `exists`— y estos ocho sitios no la responden: uno falla cerrado, otro puede ensanchar permisos, otro revienta una validación. Meterlos en el mismo PR dejaría la mitad del cambio medida y la otra mitad improvisada mientras se escribe, y desde afuera del diff las dos mitades se ven iguales. El presupuesto de 800 líneas existe para que una revisión entre entera en la cabeza de quien la hace; mezclar lo medido con lo no medido lo derrota aunque el número cierre.

1. **Unidad 8**, en cadena: **8a** la categoría `mcp/` y la selección, **8b** el directorio propio y la materialización.
   - **La Unidad 9** corre adentro de esa cadena, antes de **8a2**: reemplaza el digest-permiso por el snapshot antes de que 8a2 le dé al usuario el poder de retirar servidores sobre esa misma política.
   - **La Unidad 10** también corre adentro, entre **8a2** y **8b**: arregla el contrato del puerto de filesystem antes de que 8b agregue superficie de archivo nueva que pasaría por los mismos trece sitios sin auditar.
2. **Unidad 4.** Launcher, empaquetado de un solo archivo. Destraba la TUI.
3. **Unidades 5 y 6.** La TUI.

Ese orden se ejecutó entero. Las unidades 4, 5 y 6 están entregadas —el `zipapp` es el único punto de entrada y la TUI existe con sus pantallas de instalación y de modelos—, y con ellas el corte numerado quedó cerrado. Lo que vino después no siguió este plan y no pretende hacerlo: vive en "Lo que se agregó después del corte".

Ya entregado, en este orden: el cierre de la unidad 3 —el `.env` real del skill registry y el retiro de los marcadores sin lector—; la unidad 7, que fue temprano por ser la herramienta con la que se verifica todo lo que viene después; la **8a1**, con la categoría `mcp/` y el primer servidor instalado de verdad; la **unidad 9**, en cadena de cuatro PRs; la **8a2**, que cerró la cadena 8a con la selección del usuario y un retiro que salió genérico; y la **unidad 10**, el contrato del puerto de filesystem.

El presupuesto de revisión es de **800 líneas cambiadas por PR**. Cada unidad se mide al planificar sus tareas; la que se pase se parte en una cadena, con la estrategia definida antes de empezar a escribir código. La unidad 1 ya se midió y por eso está partida en 1a y 1b.

---

## Lo que se agregó después del corte

Las unidades de arriba son un plan y su ejecución. Lo que sigue no estaba en ese plan: son mecanismos que aparecieron entre 5.1.0 y 5.8.0, casi todos porque una instalación real mostró que el producto prometía algo que no cumplía. Se anotan acá y no dentro de una unidad para no reescribir la historia de un corte que se entregó como está escrito.

### El contrato de un MCP tiene dos mitades, y las dos responden a la misma elección

El corte dejó una sola: **la convención**, que es el cuerpo del descriptor y viaja a `_shared/mcp/<id>-convention.md` sólo si el servidor se selecciona. Es el detalle operativo —orden de herramientas, presupuesto, formatos— y se lee a demanda.

Falta la otra, que es la que hace que la primera se lea alguna vez: **la referencia fuerte**. Qué es el servidor, qué puede hacer el agente con él, y el puntero a la convención. Se paga en cada turno, así que es corta a propósito.

Vive en `content/agents/mcp/<id>.md`, y `content/agents/mcp/<id>@<agente>.md` la reemplaza para un agente cuyo encuadre lo justifique — el orquestador dice que el descubrimiento estructural en profundidad **no** es suyo, y `king-pegasus` dice lo contrario porque actúa en vez de delegar. El prompt de sistema tiene su propia versión del mismo mecanismo en `content/system-prompt/mcp/<id>.md`.

Cada agente resuelve sus secciones desde su propio `optional_mcp`, que es exactamente la lista que `select_mcp` ya poda. Eso es lo que hace que **un grant y la instrucción que le dice al agente que lo use no puedan discrepar**: salen de la misma fuente. Antes no era así, y un usuario que no elegía un servidor recibía igual los párrafos que le mandaban a leer una convención que nunca se instaló.

### Un servidor se puede atar a uno que la persona ya administra

`--mcp ID=CLAVE` le dice a Pegasus que lo que él llama `cbm` es un servidor que la instalación ya corre bajo otra clave. Concede sus herramientas y embarca su convención; **no obtiene el binario, no escribe la entrada de configuración, no toca la versión**. Existe porque la alternativa era peor: instalar el servidor de Pegasus al lado del que la persona administra deja dos versiones sobre un mismo store.

La clave se valida donde todavía es algo que alguien tipeó. Se empalma textual en reglas de permiso de los dos lados del grant, y el runtime lee `*` y `?` dentro del nombre de una regla como patrón: una clave con comodín renderiza una regla que le gana al deny baseline para todo. Una regla no se distingue de una que alguien quiso una vez que está en el mapa.

### Un servidor que la persona administra, sin descriptor ni convención, se concede a todos los agentes por igual

`--mcp ID=CLAVE` es para un servidor que Pegasus conoce: tiene descriptor, y por lo tanto convención y referencia fuerte. Falta el caso de uno que Pegasus nunca vio -- Jira, Figma, cualquier MCP que la persona instaló y administra por su cuenta. Para ese caso no hay descriptor donde declararlo: un `reaches` exigiría un descriptor y una convención que no existen, y forzarlo a esa forma haría que `_require_mcp_convention_referenced` se niegue con razón, porque ningún cuerpo de agente referencia jamás un servidor del que nadie escribió una línea.

`Install.granted_mcp` y `Agent.granted_mcp` son el campo aparte que resuelve esto: `pegasus mcp grant --cli <id> <clave>` la agrega, y `content.grant_mcp` la aplica **igual a todos los agentes**, nunca por agente -- la decisión explícita fue que agregar un MCP más no debía volverse una tarea tediosa de tocar archivo por archivo. El render escribe `<clave>*` en `tools` y `permission`, exactamente como el comodín de un servidor propio, pero después del comodín de `optional_mcp` y antes de `denied_mcp_tools`: si un servidor propio de Pegasus ya negó una herramienta puntual a un agente, un grant del usuario nunca puede reabrirla.

Se rechaza una clave que coincide con un id que Pegasus ya embarca, o con una que ya está atada: conceder ahí de nuevo, a todos los agentes por igual, borraría el recorte por agente que esa atadura ya tenía. `mcp grant` además se niega a otorgar una clave que la configuración propia de la CLI no declara -- la misma lógica de `_require_mcp_convention_referenced`, aplicada donde no hay convención que verificar: un error de tipeo no debe traducirse en un permiso que nadie nota que falta.

### El comodín de un servidor no alcanza lo que destruye

Conceder las herramientas de un servidor se hace con `<clave>*`, y esa granularidad es correcta: un descriptor no debería enumerar todo lo que un servidor expone. `withheld_tools` nombra, **por excepción**, lo que ese comodín no debe alcanzar, y el render lo escribe después del grant, que es lo único que lo hace ganar.

Lo que se retiene se decide por lo que destruye estado, no por lo que parece peligroso: `index_repository` **no** se retiene, porque la convención de CBM lo prescribe como la reparación de un índice viejo, y denegarlo rompería una regla que el producto mismo le da a sus agentes.

### Leer fuera del worktree es un permiso propio

El runtime pregunta por `external_directory` antes que por `read` cuando el destino queda fuera del árbol del proyecto, y los nombres de permiso se matchean por comodín — así que el `{"*": "deny"}` con el que abre cada agente lo alcanzaba. Todo el contrato de lazy-loading vive bajo el directorio de skills, que está fuera de todo worktree, así que estaba ilegible por construcción sin una excepción para ese directorio.

Se concede acotado a ese directorio y no al de configuración que lo contiene: ahí vive el archivo de settings, con lo que sea que la persona haya configurado. Y se gana en vez de darse: sólo lo traen las herramientas cuyo equivalente en el runtime efectivamente pregunta bajo ese nombre (`read`, `grep`, `glob`, `edit`, `write` y `bash` -- ver `EXTERNAL_DIRECTORY_TOOLS` en `render.py`).

**El incidente reportado desde uso real fue uno solo, y es el que describe la sección siguiente: la línea de base `deny` para sub-agentes.** `EXTERNAL_DIRECTORY_TOOLS` empezó con sólo `read`, `grep` y `glob`; `edit`, `write` y `bash` se agregaron después, pero eso es una corrección hacia adelante, no la respuesta a un segundo incidente reportado. Ningún agente que este catálogo distribuye hoy declara `edit`, `write` o `bash` sin también declarar `read` -- `sdd-verify`, el sub-agente que sí combina `bash` y `write`, siempre declaró `read` también (`requires_tools: [read, write, bash]`), así que siempre recibió la clave `external_directory` bajo el conjunto viejo, más angosto. Comparando el `opencode.json` renderizado antes y después de este ensanchamiento para el catálogo actual, no cambia un solo byte. Lo que sí cambia es la garantía hacia un agente futuro que declare alguna de esas tres herramientas sin `read`: con el conjunto viejo caía al `deny` exterior sin la clave `external_directory` en absoluto; con el conjunto ampliado, la recibe. Se verificó leyendo la fuente del runtime en vez de suponerla (ver el comentario de `EXTERNAL_DIRECTORY_TOOLS` en `render.py` para el detalle de `bash`, que no llama `assertExternalDirectory` como las otras cinco sino que pide el mismo permiso por su cuenta).

La segunda corrección es la que importa más. La línea de base fuera de la excepción solía no ser la misma para todo agente: un sub-agente la recibía en `deny` y un agente primario en `ask`, con el razonamiento de que un sub-agente no tiene a nadie a quien preguntarle, así que negarse de plano es mejor que colgar. Un sub-agente de verificación (`sdd-verify`) pidió correr `bash` con directorio de trabajo fuera de su worktree, con su propio permiso `bash` en `allow`, y el runtime lo rechazó en seco -- reportado desde una corrida real, ninguna prueba de este repositorio lo detectó. La razón es que ese razonamiento sobre `deny` era correcto en la letra y falso donde importa: el `ask()` del runtime devuelve su rechazo **antes** de publicar cualquier prompt en cuanto ve un `deny` de configuración, y una aprobación sólo se concatena al **final** de esa misma lista de reglas -- así que para un directorio que sólo toca la sesión de un sub-agente, nunca existe una aprobación previa que le gane a ese `deny`. No es negarse una vez: es borrar la posibilidad de preguntar para el resto de la vida del runtime, sin sesión, reinicio ni persona capaz de revertirlo. (En el motor más nuevo que el mismo proyecto ya distribuye, un `deny` de configuración se resuelve **antes** de mirar cualquier aprobación, así que ahí el rechazo es absoluto sin excepción.) La línea de base ahora es `"ask"` para todo agente, primario o sub-agente por igual -- que es además lo que el propio runtime usa como default para sus agentes -- y el split por `item.mode` se eliminó: con los dos casos resolviendo al mismo valor, mantenerlo no aportaba nada.

### Un directorio de trabajo propio es un dato que la persona declara, no una excepción que se edita a mano

La sección anterior resuelve la ruta de skills, fija y conocida en tiempo de release. Un directorio de trabajo que un agente necesita -- un worktree enlazado, un árbol de scratch fuera del proyecto -- es un hecho que Pegasus no puede conocer de antemano, y no hay forma soportada de declararlo: Pegasus reclama la entrada completa de cada agente en la configuración renderizada, así que una excepción agregada a mano la pisa el siguiente `install`/`update`.

`Install.granted_directories` y `Agent.granted_directories` siguen el mismo molde que `Install.granted_mcp` ya estableció para el problema gemelo: `pegasus directory grant --cli <id> <ruta>` la agrega, sobrevive a cada reinstalación, y `directory revoke` la quita. A diferencia de un grant de MCP, no hay colisión que rechazar -- un directorio no comparte espacio de nombres con nada que Pegasus ya renderice por agente -- así que `content.grant_directories` no tiene la lógica de `droppable` que `grant_mcp` necesita, y alcanza a todo agente por igual, sub-agentes incluidos: una necesidad de directorio propio en un sub-agente es exactamente el caso que este mecanismo existe para resolver.

La validación rechaza lo que no puede ser una ruta segura: relativa, con `..`, cualquier metacarácter de glob que el propio matcher del runtime interpreta (`*`, `?`, y también `[`/`]` por precaución -- una ruta que llega verbatim a una regla de permisos es exactamente el lugar donde conviene rechazar de más), o la raíz del filesystem -- conceder `/` renderizaría `/*`, y como el comodín del runtime cruza `/`, esa regla coincide con cualquier ruta absoluta que exista, un segundo baseline abierto de par en par con el valor contrario al que se quería escribir. También se rechaza el directorio de configuración de la CLI y cualquier ruta que sea su ancestro: ese directorio contiene el archivo de settings con lo que la persona haya configurado de sus propios servidores, y este producto ya decidió conceder sólo el subárbol de skills debajo de él, a propósito -- una ruta ancestro reabriría esa puerta por otro lado. Por el mismo motivo se rechaza también el directorio de datos del propio Pegasus (donde vive el journal): darle `write` a todo agente sobre ese directorio convertiría una escritura cualquiera en un borrado arbitrario en la próxima `uninstall`, que lee ese journal sin volver a validarlo contra el disco. Ningún otro directorio de la máquina se cierra de esta forma -- estos dos se cierran porque el propio Pegasus depende de que sigan intactos, no porque sean sensibles en abstracto. Deliberadamente **no** se valida contra el home de la persona, a diferencia de cada otra ruta que este código guarda: un directorio de trabajo legítimo puede estar en cualquier parte de la máquina.

La ruta persistida -- en el journal, en lo que reporta `grant`, en lo que compara `revoke` -- es siempre la forma normalizada que devuelve la validación (`Path(...).as_posix()`), nunca la cadena cruda que la persona tipeó: una barra final, un `.` de más o `//` repetidas colapsan a la misma forma, así que otorgar con una grafía y revocar con otra equivalente funciona.

El render escribe cada directorio concedido como `f"{ruta}/*": "allow"` en el mismo mapa `external_directory`, después del baseline y de la excepción de skills -- el orden es lo único que lo hace ganar, la misma regla de resolución que gobierna todo lo demás en ese mapa.

Con la línea de base en `"ask"` (ver la sección anterior), este permiso ya no es inalcanzable para una corrida no interactiva: bajo `--auto`, `--yolo`, o el flag del runtime que saltea permisos, `opencode run` publica el pedido y lo auto-aprueba solo, y eso alcanza también a las sesiones de sub-agentes. No hay nada que corregir ahí -- es el comportamiento correcto de un `ask`, y esos flags existen justamente para eso -- pero bajo esos flags la línea de base nueva equivale en la práctica a `allow`, lo cual es distinto de lo que valía con el `deny` anterior.

### Lo que `doctor` puede y no puede afirmar

`--start-mcp-servers` es la única forma en que `doctor` deja de ser de sólo lectura: lanza cada servidor que el journal reclama y clasifica su handshake. Un servidor **atado** no tiene entrada de configuración que lanzar, así que se reporta con estado `bound` — antes no se reportaba, y una instalación con todos sus servidores atados decía «No MCP servers configured», que no era un hueco sino una afirmación falsa.

Lo que no se afirma es más de lo que el journal sabe, y son dos cosas: a qué clave se lo ató, que nunca se registró; y que sea con certeza una atadura, porque `retire` recorre los tipos en orden alfabético y un uninstall interrumpido deja la misma forma.

`mcp_granted` es una clave propia, distinta de `mcp_bound`: una clave otorgada no es una atadura -- Pegasus no le embarca descriptor, no le concede convención, y no la instaló. Confundir las dos bajo un mismo encabezado diría que algo se ató (lo que implica que un contrato viaja con eso) cuando acá nunca se embarcó nada en absoluto.

### El journal alcanza al disco sin escribir

`install` decide "already current" contra el disco; `doctor` reporta drift contra el journal. Una edición a mano que acierte lo que una versión posterior renderiza deja las dos peleadas para siempre: no se escribe nada, el journal no se actualiza, y cada corrida repite la conclusión.

Un paso `unchanged` ya carga las dos mitades de la respuesta, así que el registro que falta no cuesta un acceso a disco. Viaja en `Applied.reconciled` y **no** en `Applied.records`, y esa separación es la corrección entera: `records` es lo que un rollback puede sacar, y una reconciliación es un artefacto que la corrida nunca escribió.

### `pegasus --version`

Lo contesta el parser y nada más: no abre un home, no lee un journal, no resuelve un adapter. El número es del binario y no de ninguna instalación suya, y una máquina con la instalación rota es exactamente donde tiene que seguir funcionando. Sólo antes del subcomando, a diferencia de `--json`: `--json` modifica un reporte y va donde va el comando que modifica, y una consulta de versión no modifica nada.

### Un asset que viaja verbatim no puede nombrar la marca

La sustitución de una distribución alcanza `.md` y `.txt`; el cuerpo de un `.py` o un `.ts` viaja tal cual. De ahí sale una regla que hasta ahora no tenía quién la hiciera cumplir: **un asset cuyo cuerpo viaja verbatim no puede nombrar la marca del motor**, porque esa marca aparecería literal en una instalación que no se llama así. Existía un guardián, pero sólo miraba `.ts` y `.js`, así que un `.json` con la marca adentro era invisible — y de hecho había uno, más una línea de docstring que una distribución venía declarando como residuo aceptado desde hacía cinco releases, con una nota que prometía el arreglo «en la próxima release del motor».

El guardián nuevo recorre **todo** lo que no sea `.md` ni `.txt` bajo `adapters/*/assets/`, deriva el conjunto del árbol y la marca de `identity.json`, y acepta el placeholder mientras rechaza el literal: `{{program_name}}` es la forma correcta de nombrar al producto y por eso no dispara. Lo que no se deriva se declara con su razón, y la lista de excepciones tiene su propio guardián que exige que cada entrada siga nombrando un archivo real, sin lo cual sería ella misma una lista capaz de acumular permisos muertos.

Dos cosas que este cambio enseñó y conviene no perder. La primera es que **encontrar el problema y saber qué hacer con él son trabajos distintos**: el guardián encontró un `"schema": "pegasus-registry-assets/v3"`, y derivarlo habría dejado muerta —en silencio, porque esa lista está exenta del chequeo de obsolescencia— una entrada que la distribución tiene declarada como token protegido. Es un identificador de esquema, de la misma familia que los `SCHEMA` de `core/journal.py` y `core/catalog.py`, y se queda literal: quedó como excepción con su motivo. La segunda es que **la primera versión del guardián exentaba por nombre de archivo y no por ruta**, así que cualquier archivo nuevo llamado igual quedaba exento gratis, en cualquier subdirectorio; lo encontró una revisión adversarial y no la suite. Es la misma forma de defecto que el guardián venía a cerrar —aprobar por un proxy en vez de por el hecho—, y apareció además en un guardián hermano, que recibió el mismo tratamiento. Un recorrido por el resto del repositorio confirmó que no hay un tercero.

### Enmendar el texto del runtime, no sólo agregar el propio

Hasta acá los plugins que este producto embarca agregaban comportamiento suyo: un registro de skills, un notificador, un reporte de estado. Ninguno tocaba lo que el runtime le dice al modelo. Esta es una línea nueva y conviene declararla como tal, con su motivo y con su límite.

El motivo es un caso real. El runtime pliega `edit`, `write` y `apply_patch` sobre un único permiso `edit` para decidir qué herramientas manda, y el comodín del mapa `tools` renderizado no lo alcanza porque ese filtro compara por clave exacta. Conceder `edit` entrega `apply_patch`, y **no hay forma de negarla** sin negar la edición entera. Su descripción abre con un imperativo —«Use the `apply_patch` tool to edit files»— y un modelo lo trató como instrucción de prioridad de desarrollador que supera al prompt de sistema: se negó a editar un archivo en otro host por SSH aunque la persona lo autorizara explícitamente, y siguió negándose después de que el prompt compartido dijera lo contrario. Su propia explicación fue la que señaló la salida: lo que lo obliga es el texto que llega **con las definiciones de herramientas**, no el que llega como prompt.

`tool.definition` es el único gancho que escribe en ese mismo canal. Se dispara donde se arma la descripción que viaja al modelo, y lo que el plugin deja en `output.description` es lo que efectivamente se manda.

**El límite, que es la parte que importa:** esto se usa cuando el texto del runtime contradice lo que el producto necesita **y no existe palanca de permisos**. No es una licencia para reescribir a gusto lo que el runtime dice. Un permiso que se puede denegar se deniega; una herramienta que se puede no conceder no se concede; recién cuando las dos están cerradas —como acá, donde la herramienta viaja atada a un permiso que sí queremos— se enmienda el texto.

Y se **agrega**, no se reemplaza. Cortar la frase imperativa exigiría acertarle a un texto del runtime que puede cambiar: el día que lo reescriban, el reemplazo dejaría de aplicar **en silencio** y parecería que el defecto volvió. Un agregado sigue siendo cierto diga lo que diga el resto de la descripción.

Hexagonalmente no hay nada nuevo: un plugin es un artefacto del runtime y vive donde ya vivían los otros, en `adapters/opencode/assets/plugins/`. El core no sabe que existe, y otro CLI traerá los suyos o ninguno. Lo que sí es nuevo es que una distribución hereda esta postura junto con el motor, sin decidirla por su cuenta.

Una trampa propia de este formato: el rebrandeo de una distribución sustituye sólo `.md` y `.txt`, así que el cuerpo de un `.ts` viaja tal cual. El nombre del archivo sí se deriva de la identidad; el texto de adentro no puede nombrar la marca del motor, o una distribución embarcaría un plugin que se presenta con el nombre equivocado.

---

---

## Identidad de producto y raíz de composición

Hasta acá el motor era, literalmente, Pegasus: el nombre, el wordmark, el directorio de datos y la
fuente de auto-actualización estaban escritos como literales en `cli.py`, `core/upgrade.py` y
`tui/wordmark.py`. Eso hacía imposible construir un binario con otro nombre sin tocar el motor, y
tocar el motor para eso es exactamente lo que este cambio existe para evitar — cualquier
organización tiene que poder producir su propia distribución sin bifurcar la fuente.

**La identidad es un dato, nunca una rama de código.** `src/pegasus/identity.json` declara
`product_id`, `display_name`, `program_name`, `wordmark_words` y un bloque `release` (plantilla de
URL del asset, nombre del binario, API de último release, página de releases). `core/identity.py`
lo parsea una sola vez — `parse()` valida charset y longitud de cada palabra del wordmark (sólo
`A-Z`/`0-9`, hasta `MAX_WORD_LENGTH` caracteres), que cada URL de `release` sea `https` con host
real (contra `urlsplit`, no un prefijo, para que `https://github.com@evil.example.com` no pase por
`github.com`), y que `binary_asset` no tenga separador de ruta ni `..`. Nunca hay un valor por
default: si `identity.json` falta o no valida, el arranque falla con `IdentityError` antes de que
cualquier comando corra.

**La versión también es un dato de identidad, obligatorio, nunca la del motor.** `identity.json`
declara su propio `version`, validado en `parse()` con el mismo charset (`SAFE_VERSION`) que
`core/upgrade.py` ya usaba para sanear el `tag_name` de un release remoto antes de construir la URL
de descarga — una sola regla, no dos que puedan divergir. No hay default a `pegasus.__version__`:
una distribución fija este motor en una versión y publica sus propios releases con una numeración
completamente distinta, así que `--version`, la comparación de `upgrade` (`already-current`) y el
valor de `pegasus_version` en `doctor --json` leen todos `identity.version`, nunca la constante del
motor — de lo contrario `--version` muestra la versión equivocada y `upgrade` nunca puede detectar
que ya está actualizado. Para el propio `identity.json` de Pegasus, un test de versión mantiene
`pyproject.toml`, `pegasus.__version__` e `identity.version` iguales entre sí; esa igualdad de tres
vías es una propiedad sólo de la distribución propia de Pegasus, nunca una regla general.

**La raíz de composición es `cli.py`.** `default_identity()` lee el `identity.json` empaquetado
(vía `importlib.resources`, igual que `core/content.py` lee `content/`) y arma el único `Identity`
congelado de la corrida; `default_runtime` lo cuelga de `Runtime.identity` y lo cablea a `argparse`
(`prog=`, `description=`, `help=`), a los mensajes de `install`/`upgrade`/`uninstall`, y a
`core/upgrade.py` como el `ReleaseSource` contra el que se auto-actualiza. `core/`, `ports/`,
`infra/` y `tui/` nunca conocen el nombre de una distribución: lo reciben como parámetro. Un test de
arquitectura (`NoProductIdentityOutsideCompositionRootTest`) recorre el AST de esos cuatro paquetes
buscando literales de string que mencionen un nombre de distribución conocido — no un `grep`, porque
la palabra "Pegasus" aparece legítimamente en decenas de docstrings y comentarios; sólo un literal
que no sea docstring cuenta como ofensor, con una lista explícita de excepciones para los
identificadores de wire format que nunca cambian entre distribuciones (`cli.SCHEMA`,
`journal-v4.json`, las claves `pegasus_version`/`pegasus_installed`, etc. — ver más abajo).

**El nombre del orquestador también es un dato de contenido, no del motor.** `content/session-start.txt`
declara qué agente abre la sesión (`core/content.py: SESSION_STARTS_IN`), así que una distribución
que renombra su orquestador lo hace en `content/`, sin tocar `core/`. Hasta la versión 5.19.0 el
adapter de OpenCode (`adapters/opencode/render.py`) tenía ese mismo nombre repetido como literal en
`AGENT_FOR_ROLE`, una segunda fuente de verdad que una distribución renombrada nunca veía: sus
comandos renderizados seguían apuntando a `pegasus-orchestrator`. La corrección hace que `render.command`
reciba el nombre del orquestador como parámetro obligatorio, leído del `Content` cargado, y el scan de
`NoProductIdentityOutsideCompositionRootTest` ahora también recorre `adapters/` (en un tuple propio,
separado del que usa `NoCliNamesOutsideAdaptersTest`, porque ese paquete legítimamente sí conoce qué
CLI es, sólo no qué distribución es).

**El wordmark se dibuja, no se elige.** `tui/wordmark.py` cubre el mismo alfabeto que
`core.identity.ALLOWED_CHARACTERS` (`A-Z` y `0-9`), verificado por un test que compara los dos
conjuntos en las dos direcciones; el renderer dibuja la cantidad de palabras que `identity` le da
(una o dos), sin ninguna rama sobre el conteo.

**`tools/build_zipapp.py --identity` es obligatorio, siempre — incluso para el propio release de
Pegasus.** Es la única forma en que "una distribución no puede olvidarse de dar su propia identidad"
sea una propiedad real y no una convención: sin el flag, `argparse` rechaza la construcción antes de
escribir un solo byte. El nombre se valida con las mismas reglas de `core/identity.py` — cargado
como módulo standalone desde el propio `--source` que se está construyendo, nunca importado del
motor que corre la build, para que la regla de validación nunca pueda divergir de la que corre el
binario resultante.

**`install.sh` también se genera por identidad, con `tools/build_installer.py`.** El instalador
shell es la última pieza de la distribución que seguía hardcodeada: vive en la raíz del repositorio
como una plantilla, con un único bloque de identidad delimitado por dos líneas `# ====...====` cerca
del principio del archivo -- la raíz de composición del lado shell, el equivalente de `cli.py` del
lado Python. `tools/build_installer.py --identity <identity.json> --out <ruta>` reemplaza sólo esas
cuatro líneas (`PRODUCT_ID`, `PRODUCT_DISPLAY_NAME`, `PRODUCT_PROGRAM_NAME`,
`PRODUCT_RELEASE_BASE_URL_DEFAULT`) por los valores de un `identity.json`, carácter por carácter
igual en el resto del archivo, y valida ese `identity.json` cargando `core/identity.py::parse()`
igual que `build_zipapp.py`. Un test, análogo en espíritu a
`NoProductIdentityOutsideCompositionRootTest` pero para shell en vez de Python, escanea todo
`install.sh` fuera de ese bloque buscando el nombre de una distribución conocida.

**Lo que nunca varía por distribución** son los identificadores de wire format que otro programa
parsea: `cli.SCHEMA`, `journal.SCHEMA`, `catalog.SCHEMA`, el nombre de archivo `journal-v4.json`,
las claves JSON `pegasus_version`/`pegasus_installed`, y las variables de entorno
`PEGASUS_SKILL_REGISTRY_BIN`/`PEGASUS_SKILL_ROOTS`/`PEGASUS_NO_UPDATE_CHECK`. Cambiarlos rompería a
cualquier programa externo que ya los interpreta; la identidad de producto vive en una capa
completamente distinta de la de esos contratos.

**No-objetivo, deliberado: un producto por usuario del sistema operativo.** Instalar dos
distribuciones bajo el mismo usuario no corrompe el journal ni el directorio de datos de ninguna de
las dos — cada una está separada por su propio `product_id`. Pero `~/.config/opencode` y su
`opencode.json` siguen siendo un recurso genuinamente compartido del cliente anfitrión, no de
Pegasus, y este cambio no los vuelve seguros para dos productos a la vez: la segunda instalación
sobreescribe lo que la primera dejó en esa configuración compartida. Esto se documenta como
comportamiento conocido, no se soluciona acá — convivencia de dos productos bajo el mismo usuario no
funciona, y no hay que dar a entender lo contrario.

## v7: FTD y la escalera de rutas

Hasta 6.1.2 Pegasus conoce dos maneras de trabajar: SDD, con preflight, artifacts, fases y `sdd-verify`, y todo lo demás, que el orquestador resuelve sin nombre. v7 le pone nombre a lo demás y agrega entre las dos un carril intermedio, **FTD — Fast-Track Development**: un cambio gobernado liviano, con un record durable en el proyecto y sin la cadena de fases. Esta sección nace con la fase 2 del diseño y suma el plan de la fase 3. Lo que presenta como decidido ya está decidido y no se reabre acá: los seis puntos que la fase 2 dejó pendientes se confirmaron el 24 de septiembre de 2026 y ya están en el cuerpo. Los cuatro puntos que agregó la fase 3 también quedaron aprobados ese día. El estado de cada confirmación, y lo único que sigue abierto, están al final, en [Confirmaciones y lo que sigue pendiente](#confirmaciones-y-lo-que-sigue-pendiente). El plan de tareas por archivo está en [Slices de v7 y su progreso](#slices-de-v7-y-su-progreso), quedó aprobado, y su columna *Estado* registra el avance.

v7 no usa el ciclo SDD. Se lleva en esta sección, como se llevaron v4, v5 y v6 en este documento, que es la forma de trabajo que v7 formaliza como FTD.

### El problema y las dos reglas de v7

La tesis cabe en una línea:

> **"No merece SDD" no equivale a "no merece ningún estado durable".**

Hoy un pedido que no es SDD termina en una respuesta o en un diff, y nada más. Si el cambio necesita un checklist, sobrevivir a una compactación o dejar evidencia agrupada, el producto no tiene dónde ponerlo, y la única salida escrita es subir a SDD, que es justo la fricción que `_shared/sdd-applicability.md` existe para sacar. Con v7, **FTD pasa a ser el carril habitual del trabajo ordinario**, aunque la superficie sea grande, y SDD queda para lo que necesita un contrato revisable antes del código. FTD no es un SDD reducido: no usa `sdd-apply` ni `sdd-verify` fuera de sus contratos.

Dos reglas gobiernan el diseño, como las dos del principio de este documento gobiernan el motor:

> **1. Decidir y ejecutar son capas distintas.**

Un archivo decide qué ruta toma un pedido; otro enseña a recorrer la ruta elegida. Ninguna frontera entre rutas tiene dos dueños, y nadie carga el procedimiento de una ruta que no va a recorrer.

> **2. El router no debe convertirse en el manual de todos los flujos.**

El cuerpo always-on del orquestador lleva sólo las pistas para saber si hace falta clasificar; la clasificación vive en un archivo que se lee cuando la ruta no es obvia, y el cómo de cada ruta en otro que se lee al recorrerla. La prueba para saber dónde va un párrafo: **¿hace falta para elegir la ruta, o sólo para recorrerla?** Lo segundo nunca va al router.

### Lo que ya existe y se conserva

Tres de las cuatro rutas ya están, y v7 las formaliza en vez de inventarlas. Todo lo que sigue se verificó contra `bb37b09`:

| Hecho | Evidencia | Qué implica para v7 |
|---|---|---|
| Tres rutas existen: una pregunta va a `pegasus-explorer`, un check a `pegasus-verifier` y un cambio chico ya decidido a `pegasus-implementer`, o lo hace el orquestador dentro de su `Direct Work Threshold` | `src/pegasus/content/agents/pegasus-orchestrator.md:33-37` (*"Is this SDD at all?"*); los tres especialistas sin fase son de `009106d` | La consulta y L0 no son nuevas; lo nuevo es FTD, su record y la escalera explícita que lo rodea |
| `_shared/sdd-applicability.md` ya es dueño del criterio: *"never by size alone"*, los casos ambiguos, el trabajo que crece hasta SDD a mitad de camino sin retroactividad (*"Do not retrofit"*) y fail-open | `sdd-applicability.md:41`, `:58`, `:63-68`; `SddApplicabilityTest` (`tests/test_orchestrator_routing.py:161`) | Se renombra y se generaliza a cuatro rutas; no se escribe desde cero |
| El `Direct Work Threshold` decide cómo se ejecuta, no qué flujo se sigue | `pegasus-orchestrator.md:15-31` | Se conserva tal cual, y se aplica después de elegir la ruta |
| El cuerpo del orquestador tiene 1409 palabras contra un techo de 1420 | `ORCHESTRATOR_WORD_CEILING` (`tests/test_orchestrator_routing.py:71`), `OrchestratorStaysSmallTest` (`:256`), `WordCeilingIsReformatProofTest` (`:262`) | Quedan 11 palabras: las pistas de routing salen de reescribir *"Is this SDD at all?"* texto por texto, no de agregar |
| `king-pegasus` no tiene techo de palabras (665 hoy) y no menciona `implementation-craft.md` ni Strict TDD | `src/pegasus/content/agents/king-pegasus.md`, leído entero | Gana techo propio en el slice (a) y la resolución de Strict TDD en el (d) |
| `sdd-applicability.md` tiene 694 palabras | `wc -w` | Es la base del techo de `flow-applicability.md` |
| `delegation-capabilities.md` no es un archivo fuente: lo generan los adapters y aterriza instalado en `_shared/` | `adapters/opencode/render.py:547`, `adapters/claudecode/render.py:329`, `core/content.py:106-113` | No entra en el renombre ni en ningún cambio de v7 |
| El cómo de Strict TDD ya es compartido e independiente de SDD | `_shared/implementation-craft.md:28`, que `pegasus-implementer.md:25` ya lee | Lo que falta es cómo saber si está activo: el slice (d) |

**El renombre no deja huérfano el archivo viejo.** Un `_shared/*.md` es un asset del directorio `_shared`, con la ruta instalada tomada del nombre del archivo en disco (`_assets()` en `core/content.py:1934`), así que renombrarlo cambia la dirección instalada. `planner.retirements()` (`src/pegasus/core/planner.py:350`) decide por dirección —tipo, target y puntero— y no por id: `_claimed_by_address` (`:283`) sólo salva la entrada cuyo id cambió con el mismo target, que no es este caso. La entrada vieja del journal no coincide con nada del render nuevo, `retirements()` la devuelve y `retire()` (`:931`) la borra. Corre en `install` (`cli.py:957`), `update` es reinstalar, y el planner no conoce CLIs, así que vale igual para los dos adapters. `tests.test_planner.RetirementsTest` (5/5) lo cubre a nivel unidad, y es el invariante que [Verificación de la arquitectura](#verificación-de-la-arquitectura) ya exige: *"Instalar retira lo que el journal reclama y el render ya no produce"*. **Falta un test de punta a punta de este renombre en disco** —instalar un render, instalar el siguiente con el archivo renombrado y comprobar que el viejo ya no está—, y entra en el slice (a).

Fuera del archivo mismo, el renombre toca cuatro referencias, ninguna fuera de `src/` y `tests/`:

| Referencia | Naturaleza |
|---|---|
| `src/pegasus/content/agents/pegasus-orchestrator.md:37` | El puntero vivo del orquestador |
| `src/pegasus/core/content.py:88` | Docstring que lista los archivos lazy de `_shared/` |
| `tests/test_orchestrator_routing.py:17`, `:37`, `:189` | Un comentario, la constante `APPLICABILITY` y un `assertIn` sobre el literal; `SddApplicabilityTest` pasa a apuntar al archivo nuevo |
| `tests/test_catalog.py:562`, `:570` | Comentarios que narran el conteo del catálogo; no afirman el nombre |

El conteo del catálogo (`tests/test_catalog.py:573`: 98 archivos, 27 claves) no se mueve con el renombre y pasa a 99 archivos con `ftd-procedure.md`. Las claves no cambian: una referencia lazy es un archivo, nunca una entrada de configuración.

**El "agent marker" de Strict TDD no está definido en ningún lado.** Sólo lo nombra `src/pegasus/content/skills/sdd-init/SKILL.md:54,62`, como primer escalón para resolver si el modo está activo; ningún archivo dice qué es ni dónde se escribe.

### Lo que enseña el historial

Pegasus se construyó casi entero como v7 propone. El proyecto empezó el 22 de julio de 2026 (`aad26ba`). Los dos únicos cambios con SDD son de v3 (`openspec/archive/v3/`) y se escribieron entre el 6 y el 8 de agosto (`853d569` a `296b943`); el 13 de agosto, días después, `8e70588` demolió el motor de v3 y mandó OpenSpec al archivo. Desde entonces v4, v5 y v6 se llevaron en este documento, sin cadena de fases.

- **Siete decisiones reales se tomaron sin SDD, y salieron bien.** Las unidades 8, 9 y 10 del corte de v4; la numeración de una versión mayor; la línea base de permisos, revisada tres veces; una reestructuración de arquitectura con un trade-off que se revirtió a mitad de camino y se resolvió con registros de decisión, un plan corto y etapas; y el diseño de v7 mismo.
- **Lo que separa a los dos cambios de v3 de esos siete no es que hubiera una decisión: casi todo tenía una.** Es que la decisión tenía que poder revisarla, antes del código, alguien que no iba a ver la implementación, o que otros iban a construir contra una spec sin estar en el cambio. Cuando quien decide ve aterrizar el código en el mismo documento vivo, y puede corregirlo, el documento cumple la función de la propuesta.
- **La continuidad entre sesiones y compactaciones nunca la dio SDD.** La dieron el documento vivo, los resúmenes de sesión en Engram y un topic estable de Engram que funciona como cola de trabajo.
- **Las reglas de evidencia salen de fallas de instrumento reales**: mediciones y checks que informaron éxito, o una cifra, y eran falsos. Están en [Reglas de evidencia de FTD](#reglas-de-evidencia-de-ftd).

Un límite de lo que el historial prueba: lo único que registra es si se usó SDD. Clasificar los demás casos como consulta, L0 o FTD es una lectura retroactiva con el vocabulario de v7, no algo que alguien decidió en su momento, y el corpus de tests la usa como semilla, no como prueba.

**Por eso `needs_reviewable_contract` reemplaza a `needs_agreement`.** Con un fact que preguntara sólo si hay una decisión que tomar, cada una de esas siete habría disparado una propuesta de SDD que la persona rechazaría —siete de unos treinta pedidos reales, casi un cuarto—, y esa fricción es la que v7 viene a sacar. Una decisión o un trade-off sin contrato revisable no cambia la ruta: se toma, se registra en *Decisions* del record FTD y se sigue. Una decisión que tiene que sobrevivir a la sesión cuenta como `needs_continuity`, así que va a FTD y no a L0. Y **la coordinación entre sesiones deja de ser disparador de SDD**: es continuidad, y la resuelven el record FTD, el documento vivo del proyecto y Engram.

### Las cuatro rutas y los routing facts

La separación obligatoria es de cuatro rutas. Las preguntas son semánticas, no una tabla de umbrales:

| Ruta | Pregunta representativa | Qué NO la decide |
|---|---|---|
| Consulta / observación | ¿El resultado buscado es información, una recomendación, una investigación o un check, sin modificar todavía el sistema? | Que el tema sea grande, urgente o afecte muchos archivos |
| L0 — cambio directo | ¿Hay una única intervención ya comprendida, sin decisión pendiente, que puede ejecutarse y demostrarse con evidencia puntual? | La cantidad de archivos, líneas, comandos o entidades afectadas |
| FTD | ¿El cambio puede cerrarse y ejecutarse sin un acuerdo formal de diseño, pero necesita continuidad, alcance explícito, checklist y evidencia durable? | La falta inicial de detalle: se investiga y se pregunta para cerrar el alcance antes de aplicar |
| SDD formal | ¿Hay que fijar, antes del código, un contrato o una decisión que tiene que poder revisar alguien que no va a estar en la implementación, o una spec contra la que otros van a construir? | Que haya una decisión o un trade-off que resolver, el tamaño del diff o el miedo a equivocarse |

Las respuestas se reducen a **cuatro routing facts**, que son a la vez el contrato entre `pegasus-explorer` y el orquestador y el vocabulario del corpus de tests:

| Fact | Pregunta |
|---|---|
| `output_is_information` | ¿El resultado buscado es información, recomendación, investigación o un check? |
| `asked_for_sdd` | ¿Pidió SDD, spec o plan explícitamente, por comando o con sus palabras? |
| `needs_reviewable_contract` | ¿Hay que fijar antes del código un contrato o una decisión que tiene que poder revisar alguien que no va a estar en la implementación, o una spec contra la que otros van a construir? |
| `needs_continuity` | ¿Necesita continuidad, checklist, handoff o evidencia durable? |

Lo único fijo es el orden en que se consultan:

1. `output_is_information` → **consulta**.
2. `asked_for_sdd` → **SDD**; el pedido explícito es la aceptación.
3. `needs_reviewable_contract` → **se propone SDD**, y se entra sólo con aceptación explícita.
4. `needs_continuity` → **FTD**.
5. Ninguna de las anteriores → **L0**.

> **El tamaño nunca es un fact.**

Ni la cantidad de archivos, ni las líneas, ni la urgencia: nada del routing puede depender de ellos. Un cambio distribuido en muchos archivos sigue siendo L0 si es una única operación trivial, atómica y demostrable; uno de dos líneas es SDD si fija un contrato que consumen otros. La cantidad de archivos puede ser pista para decidir si conviene delegar, nunca para elegir la ruta.

**Nombres, y la consulta sin número.** Los niveles se llaman L0, FTD y SDD. La consulta no lleva número ni etiqueta propia: alcanza con nombrarla en el orden de `flow-applicability.md`, porque hoy nada la identifica y nada lo necesita. **FTD se activa sólo por routing en v7**: `src/pegasus/content/commands/` no tiene infraestructura de comandos para rutas fuera de SDD, y un comando puede sumarse después sin tocar el contrato de facts.

Cuándo entra cada ruta, en corto:

- **Consulta**, cuando el output pedido termina el trabajo: explicar, comparar, investigar, auditar, revisar, correr un check o proponer sin autorización para implementar. No autoriza modificaciones ni crea artifact durable.
- **L0**, cuando, con el alcance cerrado, el cambio es trivial, atómico, mecánico y conocido, sin checklist durable, sin handoff y sin decisión que resolver. Deja un diff, evidencia puntual proporcional y un reporte honesto. **No crea record FTD ni carga el procedimiento FTD.**
- **FTD**, cuando hay intención de aplicar un cambio ya suficientemente decidido, `needs_reviewable_contract` es falso, no hacen falta varias fases ordenadas y el cambio sí merece continuidad, checklist, evidencia durable o handoff. La investigación no espera una autorización literal: investiga, pregunta para cerrar el alcance y, con una propuesta ejecutable, pide una única confirmación antes de escribir —*"Está todo definido y el alcance es X; ¿le doy?"*—. Un upgrade de dependencia con fallout conocido, una migración mecánica grande, un bug con causa confirmada, un renombre transversal o un refactor de varios módulos con el enfoque ya definido son FTD, aunque no sean chicos.
- **SDD**, cuando hay un contrato o una decisión que alguien ausente de la implementación tiene que revisar antes del código; una spec o un plan contra el que otros van a construir; una API, una autorización o un modelo de datos compartido con consumidores que no participan del cambio; varias unidades ordenadas que otros van a ejecutar; o un pedido explícito. Adentro sigue todo el flujo actual —preflight, `sdd-init`, explore a tasks, apply, verify y archive—, con delivery strategy, review budget, ChainPR y `sdd-verify` como autoridad final.

Si la ruta no es obvia, el orquestador obtiene sólo los facts que le faltan: investiga inline dentro de su threshold o delega una exploración estrecha a `pegasus-explorer`, que devuelve routing facts y no ejecuta un flujo ni crea artifacts. Todo lo que se juntó para decidir —la investigación de la consulta, los findings, la evidencia de un L0— entra como input de la ruta elegida.

### Tres capas: decidir, ejecutar y nada más en el cuerpo

La primera versión del diseño proponía un archivo de applicability por nivel, y se descartó: para cargar el correcto había que saber de antemano a qué nivel se iba, y cada frontera quedaba con dos dueños. La separación es por función, no por nivel:

| Capa | Archivo | Qué contiene | Cuándo se carga |
|---|---|---|---|
| Pistas | El cuerpo de `pegasus-orchestrator.md` y el de `king-pegasus.md` | ¿Información o intención de cambio?, ¿pidió SDD, spec o plan?, y que el resto requiere clasificar | Siempre, como hoy |
| Decidir | `src/pegasus/content/skills/_shared/flow-applicability.md`, renombre de `sdd-applicability.md` | Las preguntas de cada frontera, los cuatro facts, el orden de decisión y las promociones, con lo que el archivo viejo ya tenía de valor —casos ambiguos, crecimiento a mitad de camino, fail-open— generalizado a las cuatro rutas | Sólo cuando la ruta no es obvia |
| Ejecutar | FTD: `src/pegasus/content/skills/_shared/ftd-procedure.md`, nuevo. SDD: el preflight y los gates que ya existen. L0: casi nada | El record, las reglas de evidencia y el cierre de FTD | Sólo al recorrer esa ruta |

`ftd-procedure.md` es de la misma familia que `sdd-session-preflight.md` y `sdd-phase-common.md`: los tres dicen cómo se ejecuta algo que otro archivo ya decidió. `flow-applicability.md` pasa a ser el único dueño de la escalera y sus fronteras, y decide sin enseñar a ejecutar. El orquestador lee como mucho un archivo para decidir y uno para ejecutar, y ningún cuerpo always-on incorpora el texto de ninguno de los dos.

Los techos de palabras usan el mecanismo que ya protege al orquestador: un test de techo y un gemelo que prueba que re-envolver las líneas no lo esquiva.

| Cuerpo | Palabras hoy | Techo |
|---|---|---|
| `pegasus-orchestrator.md` | 1409 | 1420, sin cambio: la sección se reescribe dentro del margen |
| `king-pegasus.md` | 665 | Propio y nuevo, en el slice (a) |
| `flow-applicability.md` | 694, medido sobre `sdd-applicability.md` | Propio y nuevo, en el slice (a), para que no crezca a escondidas |

El valor de los dos techos nuevos no está fijado: sale de medir el texto que aterrice en el slice (a).

### Transiciones entre rutas

| Desde → hacia | Cuándo | Aceptación | Qué se preserva |
|---|---|---|---|
| Consulta → L0, FTD o SDD | La investigación dejó una propuesta ejecutable | Una consulta no autoriza cambios: *"Ya está definido X, con alcance Y; ¿le doy?"*. Hacia SDD, además, la aceptación explícita de siempre | La investigación entra como input de la ruta nueva |
| L0 → FTD | Deja de ser atómico; necesita varias tareas, otra sesión o un handoff; requiere evidencia agrupada; toca más superficie de la prevista; no se prueba con una evidencia puntual; se vuelve mantenimiento repetible; o aparece una decisión que conviene registrar | La confirmación de alcance de FTD | El record se crea desde el estado actual —qué se hizo, con qué evidencia real, qué falta—, sin fingir que FTD existía desde el inicio ni marcar checks que no se observaron |
| L0 → SDD | Aparece un `needs_reviewable_contract`. Una decisión que se toma y se ve aterrizar en el mismo record promueve a FTD, con la decisión en *Decisions* | Explícita, después de nombrar el hecho nuevo y por qué L0 ya no alcanza | Lo previo queda como exploración y evidencia de entrada; preflight y gates rigen desde la promoción |
| FTD → SDD | Aparece un `needs_reviewable_contract` o un pedido expreso de SDD, spec o plan. Dos diseños razonables o un trade-off, solos, no promueven: se deciden, se registran y el FTD sigue | Explícita, antes de entrar al ciclo | El record es input de proposal, spec y design, sin duplicar datos; SDD no se aplica retroactivamente |
| SDD → FTD o L0 | Nunca de forma automática | — | Una cancelación controlada exigiría decisión explícita, preservación honesta del estado, justificación y tests, y no entra en v7 |

Si una promoción no es obvia, se re-evalúa con el contexto disponible y, si los sistemas o contratos involucrados no están claros, se delega una exploración estrecha que devuelve routing facts. Se juzga la complejidad de decisiones y de coordinación, nunca la cantidad de archivos. Es la regla que `sdd-applicability.md:58` ya aplica al trabajo que crece hasta SDD, extendida a las dos promociones nuevas.

### Actores y readiness fuera de SDD

v7 no agrega roles ni cambia ningún `may_delegate_to`; la evolución de roles queda fuera. Lo que cambia es qué hace cada agente en las rutas nuevas:

| Agente | En v7 |
|---|---|
| `pegasus-orchestrator` | Enruta, coordina y hace él mismo los chequeos y la investigación acotada que necesita para decidir y preparar delegaciones; no es un delegador puro. Decide la ruta primero y aplica después el `Direct Work Threshold`, `may_delegate_to`, las capacidades del target y las reglas de paralelismo. No hay pipeline fijo de subagentes para L0 ni para FTD: cada handoff se justifica y nada se delega por ceremonia |
| `king-pegasus` | **Aplica a todas las rutas salvo SDD.** Como escribe, arma él mismo el record FTD; si un trabajo suyo tiene que pasar a SDD, lo dice y deriva al orquestador, sin correr el ciclo. Su `may_delegate_to: [pegasus-general]` (`king-pegasus.md:6`) no cambia |
| `pegasus-implementer` | El gemelo operativo de `sdd-apply` fuera de SDD: ejecuta L0 y FTD sin heredar preflight, artifacts ni gates exclusivos de SDD |
| `pegasus-verifier` | Sigue devolviendo sólo evidencia, nunca un veredicto de readiness |
| `pegasus-general` | El worker sin identidad de fase, usable en L0, en la investigación previa y en FTD |
| `pegasus-explorer` | Investigación read-only sin artifact de fase; en v7, además, devuelve routing facts cuando se le piden |
| `sdd-apply`, `sdd-verify` | Sin cambio: `sdd-apply` implementa tareas SDD y `sdd-verify` sigue siendo la única autoridad de readiness SDD |

**Readiness fuera de SDD: la opción (a).** El readiness de L0 y FTD lo declara quien pidió el trabajo —el orquestador, o `king-pegasus` en su propia sesión— leyendo la evidencia, que es lo que el verifier ya dice de sí mismo: *"leave the conclusion to whoever asked for it"* (`pegasus-verifier.md:17`). En FTD se ve en el record: un ítem está hecho sólo si tiene asociada una observación concreta. La separación de `009106d` se conserva tal cual: `pegasus-implementer` y `pegasus-general` pueden llamar a `pegasus-verifier` (la línea 6 de cada uno), y justamente por eso el verifier no firma:

> **Nadie que un escritor pueda alcanzar tiene autoridad para firmar.**

**Cuando quien firma también escribió** —un L0 inline del orquestador, o todo lo de `king-pegasus`—, nadie declara "listo" sin una observación registrada, y quien firma algo que escribió lo dice explícitamente en vez de presentarlo como verificación independiente. Es la extensión del *"Close the loop you open"* de `king-pegasus.md:19`, que ya cubría casi todo.

### El record FTD y dónde vive

**Ubicación: `docs/ftd/<YYYY-MM-DD>-<slug>.md` en el proyecto.** El subdirectorio propio evita pisar la documentación que el proyecto ya tenga en `docs/`. Se escribe sin preguntar nada y **se versiona con Git por defecto**. El FTD que crea `docs/ftd/` avisa una sola vez dónde quedó el record y que, si no se quiere subir, se puede excluir con `.gitignore` o con `.git/info/exclude`, que no se versiona. Detectar el primero no necesita estado guardado: es el que crea el directorio.

**Engram es el nexo, no una segunda copia.** Con Engram disponible, las decisiones, el resultado y la ruta exacta del record se guardan también ahí con el protocolo normal (`mem_save`, el resumen de sesión); es lo que permite recuperar el contexto y enlazar un FTD con una promoción posterior a SDD. Sin Engram, el record es la fuente durable y la conversación informa su ruta explícitamente. FTD no crea wiki, no compite con OpenSpec y no crea una tercera memoria; SDD conserva sin cambios su elección explícita de `openspec`, `engram`, `hybrid` o `none`.

El record tiene seis secciones:

| Sección | Qué lleva |
|---|---|
| *Intent* | Lo que el cambio quiere lograr |
| *Scope* | El alcance confirmado antes de escribir —el X del *"¿le doy?"*— |
| *Decisions* | Opcional, sólo si el cambio toma decisiones: una tabla corta de tema, decisión y motivo, como [Decisiones tomadas](#decisiones-tomadas) al principio de este documento. No repite el diff |
| *Checklist* | Los ítems del cambio; uno está hecho sólo con una observación asociada |
| *Evidence* | Los comandos textuales tal como se corrieron, con su exit status y lo que produjeron |
| *Next* | Lo que falta de este cambio, no de todos, con cada ítem en uno de tres estados |

Los tres estados de *Next* son los mismos tres libros que este documento lleva para el trabajo pendiente, y por la misma razón: una deuda que se decidió dejar no es lo mismo que una que espera.

| Estado | Qué lleva |
|---|---|
| Deuda abierta | Lo que la destraba |
| Resuelta | Su evidencia |
| Limitación aceptada | Nada que la destrabe: se decidió que se queda, y se reabre sólo si se reabre la decisión |

Dos reglas más cierran el record:

- **Las decisiones que duran se gradúan.** El record es la bitácora de un cambio: se cierra y no se corrige. Una decisión que sobrevive al cambio —una convención, una limitación aceptada, un invariante— pasa al documento vivo del proyecto, si lo tiene, o a un topic estable de Engram, y el record enlaza hacia allá. Si no hay ninguno de los dos, queda en el record y se dice. Es la diferencia de forma con este documento, que puede corregirse porque es uno solo y se lee antes de volver a escribir; un record por cambio no puede.
- ***Next* enlaza a la cola de trabajo del proyecto**, si existe como topic de Engram, en lugar de duplicarla.

**Sin límite numérico de preguntas.** Se pregunta sólo cuando la respuesta cambia alcance, criterios de aceptación, riesgos, dependencias o evidencia; nunca por ritual.

**Un escritor por vez: el record lo mantiene quien coordina el FTD**, el orquestador o `king-pegasus`. Los subagentes devuelven evidencia y él la incorpora.

### Reglas de evidencia de FTD

> **Un checkbox no es evidencia.**

Cada ítem completado se asocia a una observación concreta: test, build, exit status, check de runtime, parseo de configuración, búsqueda confirmada, smoke test o verificación visual apropiada. Un check que no se pudo correr se registra `not-run`, `blocked` o `failed`, nunca como hecho. *Evidence* guarda los comandos textuales con su exit status: además de evidencia, es la materia prima para detectar repetición en el futuro (ver [Fuera de v7](#fuera-de-v7)).

Las nueve reglas salen de mediciones o checks del historial que informaron éxito, o una cifra, y eran falsos. Viven en `ftd-procedure.md`, redactadas cortas porque ese archivo se carga en cada FTD:

1. El exit status que importa es el del comando, nunca el de un pipe que lo sigue: `if cmd | tail; then` mide `tail`.
2. Una búsqueda de X no corre donde su propio path contiene X; si no se puede evitar, se verifica antes de creer el resultado.
3. Una cifra que salió con una limitación declarada viaja con esa limitación: "N, con la limitación L" es un solo hecho.
4. Los nombres de artefactos, URLs y archivos que usa un check se derivan de la misma fuente que los produjo, nunca se tipean de memoria.
5. Una sonda necesita un brazo de control y un observable que el agente bajo prueba no pueda fabricar.
6. Un grep vacío es evidencia débil de ausencia, no prueba.
7. Un literal que coincide con la identidad de hoy es correcto por accidente: el invariante se deriva de la fuente que protege.
8. El nombre de un test verde es una afirmación: se audita que el cuerpo pruebe lo que el nombre promete.
9. Con `set -euo pipefail`, un pipe a `head -1` puede matar al productor con SIGPIPE y abortar el script en silencio.

El mismo historial dejó tres reglas más, propias de un flujo de trabajo entre repositorios que Pegasus no tiene, y no entran.

FTD tampoco impone branch automático, prohibición de worktrees, el pipeline SDD completo ni `sdd-verify`: delivery, Git y aislamiento siguen la policy existente de Pegasus.

### Strict TDD fuera de SDD

Hoy `_shared/implementation-craft.md:28` tiene el gate *"when Strict TDD Mode is active"* y `pegasus-implementer` lo lee, pero ningún archivo le dice al implementer ni a `king-pegasus` cómo saber si está activo: la resolución vive sólo en `sdd-init/SKILL.md:54-62`. Con FTD como carril principal, sin esto el carril principal saldría sin TDD. El slice (d) lo resuelve así:

1. **El flag sigue siendo por proyecto y lo sigue escribiendo `sdd-init`**, como hoy.
2. **La regla de lectura pasa a un único dueño compartido**, probablemente `implementation-craft.md`, que ya es dueño del gate. El orden: el marker explícito, si existe; el flag del proyecto, si `sdd-init` corrió (`openspec/config.yaml` o Engram); y si no hay nada escrito, el mismo default que aplicaría `sdd-init`: con test runner, activo; sin test runner, inactivo, y se dice.
3. **`sdd-init` deja de ser dueño de la regla y pasa a usarla**: sigue escribiendo el flag, pero lee la regla del mismo lugar que todos.
4. **Se resuelve una vez por sesión y viaja en el brief.** El orquestador, o `king-pegasus`, la resuelve como ya resuelve las respuestas del preflight; si el brief no la trae, el implementer la resuelve con la misma regla.
5. **Un cambio sin comportamiento** —un typo en la documentación— se registra como **`N/A: no behavior changed`**, de forma honesta, y nunca como FAILED del gate.

Qué es el marker estaba abierto. La definición propuesta está en el plan del slice (d) y espera aprobación.

### Estrategia de tests de routing

Los tests de routing son **estáticos**, y cada uno reclama sólo lo que prueba: un test que verifica que una regla está escrita no se presenta como un test de que el modelo enruta bien.

El corpus vive en `tests/fixtures/routing-corpus/cases.json` —en una subcarpeta propia, porque `tests/fixtures/` ya tiene fixtures de otras suites— y lo prueba `tests/test_flow_routing.py`. No se instala, así que no cuesta contexto en runtime. Cada caso lleva el `request`, los cuatro `facts`, la `route`, `decided_by` —una cláusula literal de `flow-applicability.md`— y `surface`; los de transición agregan `during` (`l0` o `ftd`), el hecho nuevo que dispara la promoción y si la ruta resultante requiere aceptación explícita.

```json
{
  "request": "Subí la versión de la dependencia y arreglá lo que rompa",
  "facts": {"output_is_information": false, "asked_for_sdd": false,
            "needs_reviewable_contract": false, "needs_continuity": true},
  "route": "ftd",
  "decided_by": "<cláusula literal de flow-applicability.md>",
  "surface": "large"
}
```

| Chequeo | Qué verifica | Qué atrapa |
|---|---|---|
| Coherencia | Los `facts` de cada caso llevan a su `route` según el orden de decisión | Un caso mal etiquetado |
| Trazabilidad | `decided_by` cita una cláusula que existe literalmente en `flow-applicability.md` | Una regla borrada o renombrada que deja casos huérfanos |
| Cobertura | Cada cláusula de `flow-applicability.md` tiene al menos un caso que la cita | Una regla que nada ejercita |
| Trampas por estructura | Hay casos `surface: large` que no son SDD y casos `surface: small` que sí lo son | Que el tamaño vuelva a decidir la ruta |
| Transiciones | Los casos con `during` promueven a la ruta correcta; toda entrada a SDD por `needs_reviewable_contract` requiere aceptación; ningún caso baja desde SDD | Promociones rotas y downgrades automáticos |
| Contrato de facts | `flow-applicability.md` declara exactamente los campos que usa el corpus | Que el contrato explorer → orquestador y el corpus diverjan |

**El corpus sale de pedidos reales.** La exploración del historial dejó unos treinta candidatos de todas las rutas, y entran parafraseados y anonimizados: sin nombres de productos distintos de Pegasus, personas, equipos, instituciones, hosts ni correos. La procedencia de cada caso y la clasificación retroactiva de la exploración no entran al corpus. Tiene que incluir, como mínimo:

- cambios grandes que no son SDD;
- un cambio chico que sí es SDD, como dos líneas de un contrato que consumen otros;
- los siete casos del historial con una decisión real y sin contrato revisable, que van a FTD;
- promociones reales.

`surface` es una carnada: se anota para demostrar que no importó. Una regla de tamaño no se puede escribir en el vocabulario de los cuatro facts, así que la cobertura la rechaza: no hay caso coherente que pueda citarla.

Además del corpus: los tests de techo, con su gemelo, para `flow-applicability.md` y `king-pegasus.md`; un test de lazy-load que fija que ningún cuerpo always-on incorpora el texto de `flow-applicability.md` ni de `ftd-procedure.md`, y que el procedimiento sólo se nombra en la salida de la ruta FTD de `flow-applicability.md`; y el test de punta a punta del renombre.

**Residuo declarado.** El corpus **no prueba** que el modelo, ante un pedido real, responda bien los cuatro facts, y eso queda escrito como no cubierto. Si se quiere medir, las `request` del corpus se corren a mano contra un modelo real y se comparan los facts, fuera de la suite, como los checks de release.

**Lo que no se copia del harness externo estudiado como referencia.** Su routing tenía justamente el defecto que este diseño evita: el corpus se declaraba puntuado por un eval de comportamiento que en realidad leía otro archivo, así que lo único que lo tocaba era un chequeo de forma; un test aprobaba si una palabra de tamaño aparecía en la justificación, y probaba la palabra y no el caso; y los casos se puntuaban con un ranker léxico, por coincidencia de palabras entre pedido y descripción. De ahí se toma sólo la idea de un corpus con la ruta esperada de cada caso.

### Compatibilidad, permisos y seguridad

- **Wire formats**: no cambia ninguno. `cli.SCHEMA`, `journal.SCHEMA`, `catalog.SCHEMA`, `journal-v4.json` y las claves y variables de entorno que enumera [Identidad de producto y raíz de composición](#identidad-de-producto-y-raíz-de-composición) quedan como están.
- **Instalaciones existentes**: reinstalar retira `_shared/sdd-applicability.md` y escribe `flow-applicability.md` y `ftd-procedure.md` por el mecanismo de retiro que ya existe, en los dos adapters; `uninstall` retira lo que el journal reclame en ese momento.
- **Quien no use FTD**: sin impacto, más allá del texto que cambia en dos cuerpos que ya tienen tests y de `docs/ftd/`, que aparece recién con el primer FTD.
- **SDD**: nada cambia adentro del ciclo. Cambia cómo se llega: por pedido explícito, o por un `needs_reviewable_contract` propuesto y aceptado.
- **Permisos**: v7 no agrega herramientas, grants MCP ni directorios. `docs/ftd/` se escribe dentro del proyecto con el `edit` y el `write` que el agente que coordina ya tiene, y ningún `may_delegate_to` cambia.
- **Controles que no se debilitan**: CBM es inteligencia de código, no evidencia de runtime; `sdd-verify` sigue siendo la autoridad exclusiva de readiness SDD; ChainPR y review budget siguen rigiendo SDD; se conservan `may_delegate_to`, los permisos por agente y los grants de MCP y de directorios; el journal, los snapshots, el restore y el ownership; la delivery strategy, el aislamiento y las políticas de worktree; y el techo de palabras del orquestador.
- **Versión**: mayor o menor es una decisión de release, y sigue pendiente (ver al final).

### Riesgos y rollback

| Riesgo | Mitigación |
|---|---|
| El orquestador pasa su techo al reescribir *"Is this SDD at all?"* | La reescritura es texto por texto, con 11 palabras de margen, y `OrchestratorStaysSmallTest` falla si no alcanza |
| `flow-applicability.md` crece hasta volverse el manual de todos los flujos | Techo propio, y el formato del record, la evidencia y el cierre viven en `ftd-procedure.md` |
| El tamaño vuelve a decidir la ruta por la puerta de atrás | Las trampas del corpus y la cobertura: una regla de tamaño no tiene caso coherente que la cite |
| Un test de routing se lee como prueba de que el modelo enruta bien | El residuo declarado, escrito en esta sección y en el corpus |
| El renombre deja `sdd-applicability.md` huérfano en una instalación existente | El retiro por dirección, y el test de punta a punta del slice (a) |
| FTD se vuelve ceremonia para lo que es L0 | L0 no crea record ni carga el procedimiento, y el corpus lleva casos L0 que lo fijan |
| El carril principal sale sin TDD | El slice (d): una regla de lectura, resuelta una vez por sesión |
| *Evidence* sube al repositorio algo que no debía: los records se versionan por defecto y guardan salidas textuales | El aviso único con `.gitignore` y `.git/info/exclude`. Que `ftd-procedure.md` prohíba además copiar secretos o el contenido de archivos sensibles a *Evidence* es la tarea b4, propuesta y pendiente de aprobación |

**Rollback.** v7 es contenido y tests, sin wire formats nuevos: volver atrás es reinstalar con el binario de una versión anterior, cuyo render ya no produce `flow-applicability.md` ni `ftd-procedure.md`, así que el mismo retiro por dirección los borra y `sdd-applicability.md` vuelve a escribirse. Los records que ya estén en `docs/ftd/` son archivos del proyecto, no de Pegasus: el journal no los reclama y ningún rollback los toca.

### Criterios de aceptación de v7

Cada criterio se comprueba con un test o un comando, no con una lectura:

| # | Criterio | Cómo se comprueba |
|---|---|---|
| 1 | `src/pegasus/content/skills/_shared/sdd-applicability.md` no existe y `flow-applicability.md` sí | `test -e` sobre las dos rutas |
| 2 | `grep -rn sdd-applicability src/` no devuelve nada, y en `tests/` sólo quedan, si quedan, comentarios que narran la historia del conteo del catálogo | El grep |
| 3 | `flow-applicability.md` declara exactamente los cuatro facts y el orden de decisión de cinco pasos | El chequeo de contrato de facts de `tests/test_flow_routing.py` |
| 4 | El corpus pasa coherencia, trazabilidad y cobertura, e incluye al menos un caso `large` que no es SDD, uno `small` que sí lo es, los siete casos de decisión sin contrato en FTD y promociones desde L0 y desde FTD | `tests/test_flow_routing.py` |
| 5 | Toda entrada a SDD por `needs_reviewable_contract` requiere aceptación explícita, y ningún caso sale de SDD | El chequeo de transiciones |
| 6 | El cuerpo del orquestador sigue en 1420 palabras o menos; `king-pegasus.md` y `flow-applicability.md` tienen techo propio, cada uno con su gemelo contra el re-envolver | `OrchestratorStaysSmallTest` y sus equivalentes nuevos |
| 7 | Ningún cuerpo always-on incorpora el texto de `flow-applicability.md` ni de `ftd-procedure.md`, y `ftd-procedure.md` sólo se nombra en la salida de la ruta FTD de `flow-applicability.md`, nunca desde un cuerpo always-on | El test de lazy-load |
| 8 | Instalar un render y después otro con el archivo renombrado deja el viejo ausente del disco, en los dos adapters | El test de punta a punta del slice (a) |
| 9 | El catálogo cuenta 99 archivos y 27 claves | `tests/test_catalog.py` |
| 10 | `ftd-procedure.md` fija la ruta `docs/ftd/<YYYY-MM-DD>-<slug>.md`, el aviso único, las seis secciones, los tres estados de *Next*, la graduación de decisiones y las nueve reglas de evidencia | Tests de contenido del slice (b) sobre el texto del archivo |
| 11 | La regla de lectura de Strict TDD vive en un único archivo; `sdd-init`, `sdd-apply`, `sdd-verify`, `king-pegasus` y `pegasus-implementer` la referencian en vez de repetirla, el preflight y el procedimiento FTD la pasan en el brief, y `N/A: no behavior changed` figura como resultado válido del gate | Tests de contenido del slice (d) |
| 12 | `pegasus-verifier` sigue sin emitir veredicto y ningún `may_delegate_to` cambia | `tests/test_phase_less_specialists.py` y el diff del frontmatter de los agentes |
| 13 | La suite completa pasa | `PYTHONPATH=src:tests .venv/bin/python3 -m unittest discover -s tests -q` |

### Slices de v7 y su progreso

Los slices van de (a) a (d). El plan de la fase 3 sigue a esta tabla y quedó aprobado el 24 de septiembre de 2026. La tabla es donde se anota el progreso de cada slice a medida que aterrice, con su commit y su evidencia, igual que [Deudas resueltas](#deudas-resueltas) lleva lo que se cerró:

| Slice | Contenido | Estado |
|---|---|---|
| (a) Escalera y routing | `flow-applicability.md` —renombre y ampliación, con techo—; pistas mínimas en el orquestador, texto por texto dentro de su techo, y en `king-pegasus`, que gana techo propio; routing facts en `pegasus-explorer`; el corpus y sus tests; y el test de punta a punta del renombre | **Cerrado.** a1–a4 en `c7894ef`: corpus de 48 casos con citas que coinciden con la ruta, test de punta a punta del renombre en los dos adapters, `flow-applicability.md` (1026 palabras) y orquestador en 1398; suite 2938 contra la base de 2892. a5–a6 en `72c363d`: el puntero de `king-pegasus` a la escalera con su fail-open y la derivación de SDD al orquestador, y los techos de `flow-applicability.md` (1061) y `king-pegasus.md` (783), medidos más las reservas de b5, c3 y d5; suite 2945. a7: `pegasus-explorer` devuelve los routing facts cuando el brief los pide y no elige la ruta; el chequeo es de mundo cerrado, porque tres chequeos de negación léxica se dejaron engañar en este slice (469 de 516 palabras). Cierre: catálogo en (98, 27), el nombre viejo solo en la constante del test del renombre, el renombre retirado en los dos adapters, orquestador en 1398; suite 2954 |
| (b) Record FTD y persistencia | `ftd-procedure.md`, `docs/ftd/`, el aviso único, el enlace con Engram, *Decisions*, *Next* con tres estados, la graduación de decisiones y las reglas de evidencia | **Cerrado.** b1–b5 en `238e4e8`: `ftd-procedure.md` (880 palabras) con el record, *Next* en tres estados, la graduación, Engram, las nueve reglas de evidencia y la de secretos; el único puntero desde la salida FTD de la escalera (1058 de 1061); catálogo en (99, 27); suite 2986. b6: `docs/metodologia.md` (las cuatro rutas, *FTD y su record*, *Roles y límites*) y `MANUAL.md` (*Usarlo todos los días*): FTD como carril habitual, `docs/ftd/` y cómo excluirlo, y SDD solo con un contrato revisable; suite 2986 |
| (c) Ajuste de roles | `pegasus-implementer`, `pegasus-verifier` y `king-pegasus` alineados con la opción (a) de readiness y con el record | **Cerrado.** El orquestador acota *«until `sdd-verify` has spoken»* a SDD y declara el readiness de L0 y FTD como quien pidió, desde lo observado, diciendo si firma lo que escribió (1416 de 1420); `king-pegasus` dice lo mismo junto a *«Close the loop you open»* y lleva él mismo su record (755 de 783); implementer y general devuelven evidencia para el record de quien coordina; `pegasus-verifier.md` sin diff y `ReadinessAuthorityScopeTest` sin tocar |
| (d) Strict TDD fuera de SDD | La regla de lectura con un solo dueño, su resolución por sesión en el brief y `N/A: no behavior changed` | **Cerrado.** d1–d4 en `f943ce2`: la regla de lectura y el marker viven solo en `implementation-craft.md` (975 palabras), y `sdd-init`, `sdd-apply` y `sdd-verify` la señalan; `STRICT TDD MODE IS ACTIVE` ya no está en `src/`; un brief sin la grafía reconocida se resuelve con la regla, nunca como modo standard; ningún archivo embarcado trae un marker suelto, tampoco como encabezado ni celda de tabla; suite 3011. d5: el preflight de SDD y el procedimiento FTD resuelven el modo una vez por sesión y lo mandan en cada brief de implementación como `Strict TDD Mode: <enabled|disabled>`; `king-pegasus` lo resuelve en su propia sesión (780 de 783); el cuerpo del orquestador no cambia. d6: *TDD: cuándo aplica* en `docs/metodologia.md`, con el marker y `N/A: no behavior changed`; suite 3016 |

#### Requisitos verificables por ruta y transición

Todos se comprueban con tests estáticos: el corpus y el texto de los archivos, nunca una corrida contra un modelo.

| # | Requisito | Lo verifica |
|---|---|---|
| R1 | Consulta: `output_is_information` verdadero lleva a la consulta, valgan lo que valgan los otros tres facts, y la cláusula dice que no autoriza cambios ni crea artifact | `CoherenceTest`; `FlowApplicabilityTest` sobre la cláusula |
| R2 | L0: los cuatro facts falsos llevan a L0, y la cláusula de L0 no nombra el record ni `ftd-procedure.md` | `CoherenceTest`; `ProcedureIsLazyTest` |
| R3 | FTD: `needs_continuity` sin los anteriores lleva a FTD; los siete casos de decisión sin contrato revisable van a FTD; la entrada pide la confirmación de alcance | `CoherenceTest`, `SizeTrapTest`; `FlowApplicabilityTest` |
| R4 | SDD por pedido: `asked_for_sdd` lleva a SDD sin otra aceptación, porque el pedido lo es | `CoherenceTest`, `TransitionTest` |
| R5 | SDD por contrato: `needs_reviewable_contract` propone SDD y exige aceptación explícita | `TransitionTest` (`requires_acceptance`) |
| R6 | El tamaño no decide: hay casos `large` que no son SDD y `small` que sí, y ninguna cláusula citable habla de tamaño | `SizeTrapTest`, `CoverageTest` |
| T1 | Consulta → cambio: la escalera dice que una consulta no autoriza escribir y nombra la confirmación única | `FlowApplicabilityTest` |
| T2 | L0 → FTD: con `new_fact: needs_continuity`, o cuando aparece una decisión sin contrato revisable | `TransitionTest` |
| T3 | L0 → SDD: sólo con `new_fact: needs_reviewable_contract`, y con aceptación | `TransitionTest` |
| T4 | FTD → SDD: sólo con `needs_reviewable_contract` o `asked_for_sdd`; un trade-off solo deja el caso en FTD | `TransitionTest` |
| T5 | Sin bajada: ningún caso tiene `during: sdd`, y el esquema lo rechaza | `CorpusSchemaTest`, `TransitionTest` |
| P1 | Presupuesto y lazy-load: los tres cuerpos tienen techo, y ningún cuerpo always-on nombra el procedimiento | a6, `ProcedureIsLazyTest` |

Cada tarea escribe primero su test y lo ve fallar. Donde el guardia ya se cumple al escribirlo —un techo, una ausencia—, el rojo se muestra por mutación: se rompe en memoria lo que protege, se ve fallar y la corrida queda en la evidencia. Donde la tarea no cambia comportamiento, se registra `N/A: no behavior changed`. Todos los comandos corren desde la raíz con `PYTHONPATH=src:tests .venv/bin/python3 -m unittest`, abreviado `unittest` en las tablas.

#### Slice (a) — escalera y routing

| # | Tarea | Archivos | Test primero (rojo) | Evidencia de cierre | Depende de |
|---|---|---|---|---|---|
| a1 | Corpus y su test | `tests/fixtures/routing-corpus/cases.json` y `tests/test_flow_routing.py`, nuevos | `CorpusSchemaTest` —claves exactas `request`, `facts`, `route`, `decided_by`, `surface`, más `during`, `new_fact` y `requires_acceptance` en las transiciones; ninguna clave de procedencia; `route` en `query`, `l0`, `ftd`, `sdd`; `during` en `query`, `l0`, `ftd` —la consulta se sumó en la revisión, porque la transición Consulta → L0, FTD o SDD es parte del diseño y sin ella su cláusula solo podía citarse de adorno—; toda cita tiene que coincidir con la ruta del caso, y una promoción solo la cita una transición desde su origen hacia uno de sus destinos—, `CoherenceTest`, `TraceabilityTest`, `CoverageTest`, `SizeTrapTest`, `TransitionTest` y `FactsContractTest`. Las cláusulas citables se derivan del archivo —los ítems de lista de sus secciones de decisión—, nunca de una lista retipeada en el test. Rojo: `flow-applicability.md` no existe | `unittest tests.test_flow_routing -v`: rojo antes de a3, verde después | — |
| a2 | Test de punta a punta del renombre | `tests/test_shared_reference_rename_migration.py`, nuevo, sobre el arnés de `tests/test_identity_rename_migration.py` (`RealHomeTestCase`, `run_cli`, `RenamingTheInstalledIdentityMigratesArtifactsTest`) y el de `tests/test_cli_claudecode.py` | Una clase por adapter, `opencode` y `claudecode`: instala con el contenido real cuyo asset de `_shared` se llama `sdd-applicability.md` —derivado de `content_module.load()` con `dataclasses.replace` e inyectado con `patch("pegasus.core.content.load", ...)`, como en `tests/test_cli_progress.py:146`—, corre `update` con el contenido real y afirma que el viejo no está en disco, que el nuevo sí, que el journal ya no reclama el viejo y que el reporte de `update` lo da por retirado. Rojo: no existe `flow-applicability.md` | `unittest tests.test_shared_reference_rename_migration -v`: rojo antes de a3 y verde después, en los dos adapters | — |
| a3 | Renombre y reescritura de la escalera | `git mv` de `src/pegasus/content/skills/_shared/sdd-applicability.md` a `flow-applicability.md`, con su texto llevado a cuatro rutas (`## Routing facts`, el orden de decisión, una cláusula por ruta, las promociones, los casos ambiguos, el crecimiento a mitad de camino y el fail-open); `pegasus-orchestrator.md:33-37`, reescrito texto por texto; `tests/test_orchestrator_routing.py:17`, `:37` y `:161-205` | `SddApplicabilityTest` pasa a `FlowApplicabilityTest` sobre la ruta nueva y suma que el archivo no liste como señal de SDD una decisión, un trade-off, cruzar sesiones ni un record que sobreviva a la sesión, y que el orquestador ya no diga que un record que sobrevive a la sesión es SDD; `APPLICABILITY_NEEDLE` sigue en un solo archivo, y los tres especialistas siguen nombrados en la prosa. Rojo: la ruta nueva no existe | `unittest tests.test_orchestrator_routing tests.test_flow_routing tests.test_shared_reference_rename_migration tests.test_skill_references tests.test_adapter_reference_integrity` verde; `wc -w` del orquestador ≤ 1400, para dejarle margen a (c) | a1, a2 |
| a4 | Referencias restantes | `src/pegasus/core/content.py:88` (docstring); `tests/test_catalog.py:562` y `:570` (comentarios) | `N/A: no behavior changed` | `TheRetiredNameLivesOnlyInOldNameTest` verde: el nombre viejo aparece solo en la constante `OLD_NAME` del test del renombre, que lo necesita para instalar el contenido anterior (el criterio original, un `git grep` vacío, era imposible de cumplir: ese test tiene que nombrar el archivo viejo); `unittest tests.test_catalog` sigue en (98, 27) | a3 |
| a5 | Pistas mínimas en `king-pegasus` | `src/pegasus/content/agents/king-pegasus.md`, `## Rules` | `KingPegasusRoutesTest` en `tests/test_persona_split.py`: la prosa nombra `{{skills_root}}/_shared/flow-applicability.md` con su fail-open (*"missing or unreadable"*), dice que un trabajo que pasa a SDD se deriva al orquestador y no contiene `APPLICABILITY_NEEDLE`. Rojo: nada de eso está | `unittest tests.test_persona_split` verde, `PersonaTest` intacto | a3 |
| a6 | Techos de `flow-applicability.md` y `king-pegasus.md` | `tests/test_orchestrator_routing.py`: `FLOW_APPLICABILITY_WORD_CEILING`, `KING_PEGASUS_WORD_CEILING`, `FlowApplicabilityStaysSmallTest`, `KingPegasusStaysSmallTest`, y `WordCeilingIsReformatProofTest` recorriendo los tres cuerpos con `subTest` | Rojo por mutación: sumar en memoria palabras por encima de cada techo lo pone rojo | Valores medidos después de a3 y a5, con el margen para el puntero de b5 y las frases de c3 y d5 escrito en el comentario de cada constante, como el de `ORCHESTRATOR_WORD_CEILING` | a3, a5 |
| a7 | Routing facts en `pegasus-explorer` | `src/pegasus/content/agents/pegasus-explorer.md`, `## Result identity` | `ExplorerReturnsRoutingFactsTest` en `tests/test_flow_routing.py`: la prosa nombra exactamente los facts de `## Routing facts` —conjunto derivado de `flow-applicability.md`—, pide cada uno como verdadero o falso con su evidencia y dice que la ruta no la elige el explorer. Rojo: la prosa no nombra ningún fact | `unittest tests.test_flow_routing tests.test_phase_less_specialists` verde; el cuerpo sigue bajo `BODY_WORD_CEILING` = 516 (`tests/test_phase_less_specialists.py:94`; hoy 417) | a3 |

El corpus arranca con unos treinta casos sacados de los candidatos del historial. Los que ya están parafraseados se reescriben donde nombran otro producto, una persona o un equipo, o se descartan, y la procedencia no entra nunca. La anonimización no puede ser un test con una lista de nombres, porque esa lista metería los nombres al repositorio: la cubren el esquema, que no admite un campo de procedencia, y la revisión independiente.

**Cierre propio de (a):** el catálogo sigue en (98, 27), `TheRetiredNameLivesOnlyInOldNameTest` está verde, a2 está verde en los dos adapters y el orquestador queda en 1400 palabras o menos.

#### Slice (b) — record FTD y persistencia

| # | Tarea | Archivos | Test primero (rojo) | Evidencia de cierre | Depende de |
|---|---|---|---|---|---|
| b1 | Tests del procedimiento | `tests/test_ftd_procedure.py`, nuevo | `FtdProcedureConventionsTest` (existe, con `## Scope`, `## Authority` y fail-open); `RecordTemplateTest` (plantilla con *Intent*, *Scope*, *Decisions*, *Checklist*, *Evidence* y *Next*, en ese orden, con *Decisions* opcional); `NextStatesTest` (los tres estados); `GraduationTest` (documento vivo o topic estable de Engram, enlace desde el record, y qué se hace si no hay ninguno); `PromotionIntoFtdTest` (el record nace del estado actual y no marca checks no observados); `EvidenceRulesTest` (*"A checkbox is not evidence"*, `not-run`, `blocked` y `failed`, comandos textuales con exit status, nueve reglas numeradas); `RecordLocationTest` (`docs/ftd/<YYYY-MM-DD>-<slug>.md`, `.gitignore` y `.git/info/exclude`, aviso sólo al crear el directorio); `EngramLinkTest` (la ruta exacta del record, redactado defensivo para cuando Engram no está); `ProcedureIsLazyTest` (ningún cuerpo always-on —el orquestador, `king-pegasus`, el prompt de sistema— nombra `ftd-procedure.md`; el único archivo de contenido que lo nombra es `flow-applicability.md`, en la salida de la ruta FTD; una frase distintiva del procedimiento vive sólo en él). Rojo: el archivo no existe | `unittest tests.test_ftd_procedure -v`: rojo antes de b3 | a3 |
| b2 | Conteo del catálogo | `tests/test_catalog.py:573`, a `(99, 27)`, con su comentario *"99, not 98"* | La aserción cambiada es el rojo: falla con 98 hasta b3 | `unittest tests.test_catalog` verde después de b3 | — |
| b3 | El procedimiento | `src/pegasus/content/skills/_shared/ftd-procedure.md`, nuevo, en inglés | b1 y b2 | `unittest tests.test_ftd_procedure tests.test_catalog tests.test_skill_references tests.test_adapter_reference_integrity tests.test_engram_convention` verde; `EngramProjectArgumentTest` impide templar el argumento de proyecto | b1, b2 |
| b4 | Secretos fuera de *Evidence* (aprobada el 24 de septiembre de 2026) | `ftd-procedure.md`: *Evidence* nunca copia secretos ni el contenido de archivos sensibles; el comando se registra con su exit status y la salida que los traiga se omite, diciendo que se omitió | `SecretsRuleTest` en `tests/test_ftd_procedure.py`. Rojo: la regla no está | `unittest tests.test_ftd_procedure` verde | b3 |
| b5 | Puntero desde la escalera | `flow-applicability.md`, la cláusula de salida de la ruta FTD | `ProcedureIsLazyTest` exige ese único puntero; rojo hasta que exista | `unittest tests.test_flow_routing tests.test_ftd_procedure` verde: si la cláusula citada cambió, los `decided_by` se actualizan en el mismo commit; `FlowApplicabilityStaysSmallTest` verde | b3, a6 |
| b6 | Documentación de uso | `docs/metodologia.md` (*El recorrido normal*, *Roles y límites* y una sección breve sobre FTD y su record) y `MANUAL.md` (*Usarlo todos los días*): las cuatro rutas, FTD como carril habitual, `docs/ftd/` y cómo excluirlo | `N/A: no behavior changed` | `.venv/bin/python3 tools/check_docs_links.py` da PASS | b3 |

**Cierre propio de (b):** el catálogo en (99, 27) y `ProcedureIsLazyTest` verde. b4 se aprobó y entra con `SecretsRuleTest`.

#### Slice (c) — roles y readiness

| # | Tarea | Archivos | Test primero (rojo) | Evidencia de cierre | Depende de |
|---|---|---|---|---|---|
| c1 | Tests de readiness fuera de SDD | `tests/test_orchestrator_routing.py` (`ReadinessOutsideSddTest`), `tests/test_persona_split.py` (`PersonaTest`), `tests/test_phase_less_specialists.py` (`WhatEachOneReturnsTest`) | El orquestador dice que en L0 y FTD el readiness lo declara quien pidió, leyendo evidencia observada, y que quien firma lo que escribió lo dice; *"until `sdd-verify` has spoken"* queda acotado a SDD en su misma oración; `king-pegasus` dice lo mismo junto a *"Close the loop you open"*; `pegasus-implementer` y `pegasus-general` dicen que el record lo lleva quien coordina y que ellos devuelven evidencia. Rojo: ninguna frase está | Los tres módulos, rojos antes de c2-c4 | b3 |
| c2 | Orquestador | `pegasus-orchestrator.md:98-100`, la viñeta *"Warmth is never a readiness claim"*, texto por texto | c1 | `OrchestratorStaysSmallTest` ≤ 1420 y `ReadinessAuthorityScopeTest` (`tests/test_readiness_authority_scope.py`) verdes: la frase nueva no reclama autoridad, porque ese guardia sólo admite la afirmación en `sdd-verify` y en `pegasus-orchestrator.md:47` | c1, a3 |
| c3 | `king-pegasus` | `king-pegasus.md:19`, y la regla de que arma él mismo el record, al que llega por `flow-applicability.md` | c1 | `KingPegasusStaysSmallTest` y `PersonaTest` verdes | c1, a6 |
| c4 | Implementer, general y verifier | `pegasus-implementer.md` y `pegasus-general.md`, `## Result identity`; `pegasus-verifier.md` sin cambio | c1 | `unittest tests.test_phase_less_specialists tests.test_general_fan_out_checkpoint` verde, con `BODY_WORD_CEILING` = 516 y `GENERAL_WORD_CEILING` = 556; `git diff --stat -- src/pegasus/content/agents/pegasus-verifier.md` vacío; `WhatEachOneReturnsTest` y `RenderedPermissionTest` siguen probando que el verifier no firma ni escribe | c1 |

**Cierre propio de (c):** `pegasus-verifier.md` sin diff, y `ReadinessAuthorityScopeTest` y `WhatEachOneReturnsTest` verdes sin haberlos tocado.

#### Slice (d) — Strict TDD fuera de SDD

La regla está repetida hoy en tres lectores, no en uno: `sdd-init/SKILL.md:54-56` y `:62`, el paso 3 de `sdd-apply/SKILL.md:110-139` y las puertas de `sdd-verify/SKILL.md:43-45`. Esta última espera que el orquestador diga `STRICT TDD MODE IS ACTIVE`, y ningún archivo embarcado lo dice.

| # | Tarea | Archivos | Test primero (rojo) | Evidencia de cierre | Depende de |
|---|---|---|---|---|---|
| d1 | Tests de la regla compartida | `tests/test_craft_extraction.py`: `CraftIsNotRestatedTest` y una `StrictTddResolutionTest` nueva | La regla de lectura vive sólo en `implementation-craft.md` (una frase distintiva, con `occurrences` igual a ese archivo); `sdd-init`, `sdd-apply`, `sdd-verify`, `king-pegasus` y `pegasus-implementer` la señalan en vez de repetirla; las filas de `sdd-init/SKILL.md:54-56` y el paso `:62` ya no resuelven; la puerta de `sdd-verify/SKILL.md:43` usa la grafía del brief; `N/A: no behavior changed` figura como resultado válido del gate; la grafía del marker está escrita como literal en `implementation-craft.md`, y ningún archivo embarcado la trae como línea suelta, así que Pegasus nunca activa el modo en nombre de la persona. Rojo: nada de eso está | `unittest tests.test_craft_extraction -v`: rojo | — |
| d2 | La regla y el marker | `src/pegasus/content/skills/_shared/implementation-craft.md`: una subsección nueva antes de *Strict TDD Hard Gate* (`:28`) | d1 | `unittest tests.test_craft_extraction tests.test_strict_tdd_red_evidence tests.test_phase_less_specialists` verde (`CRAFT_NEEDLE` sigue en un solo archivo) | d1 |
| d3 | `sdd-init` pasa a usar la regla | `src/pegasus/content/skills/sdd-init/SKILL.md:54-56` y `:62`; sigue escribiendo `strict_tdd` en `openspec/config.yaml` y en `sdd/{project}/testing-capabilities` (`references/init-details.md:38`, `:59`) | d1 | `unittest tests.test_craft_extraction tests.test_sdd_phase_macros` verde | d2 |
| d4 | Los otros dos lectores | `src/pegasus/content/skills/sdd-apply/SKILL.md:110-139`: primero el valor del brief, después la regla; `src/pegasus/content/skills/sdd-verify/SKILL.md:43-45` | d1 | `unittest tests.test_craft_extraction tests.test_strict_tdd_red_evidence` verde | d2 |
| d5 | Una vez por sesión, en el brief | `_shared/sdd-session-preflight.md`, junto a `:58`, que ya manda `Artifact store mode` a cada lanzamiento; `_shared/ftd-procedure.md`; `king-pegasus.md`, que nombra `implementation-craft.md` y resuelve el modo en su propia sesión. El cuerpo del orquestador no cambia | `StrictTddTravelsInTheBriefTest` en `tests/test_craft_extraction.py`: el preflight y el procedimiento FTD mandan `Strict TDD Mode` en cada brief de implementación, y `king-pegasus` nombra `_shared/implementation-craft.md`. Rojo: no está | `unittest tests.test_craft_extraction tests.test_ftd_procedure tests.test_orchestrator_routing` verde, `KingPegasusStaysSmallTest` incluido | d2, b3, a6 |
| d6 | Documentación | `docs/metodologia.md`, *TDD: cuándo aplica*: la regla ya no depende de `sdd-init`; el marker y `N/A: no behavior changed` | `N/A: no behavior changed` | `.venv/bin/python3 tools/check_docs_links.py` da PASS | d2 |

En L0 el orquestador no carga ni el preflight ni el procedimiento, así que no resuelve el modo: lo resuelve el implementer con la misma regla, que es el respaldo que la decisión ya prevé para cuando el brief no lo trae. Con eso el cuerpo del orquestador no gasta ni una palabra en (d).

**Qué es el agent marker** (aprobado el 24 de septiembre de 2026, incluida la variante en negrita). Hoy `sdd-init/SKILL.md:54` lo pone primero (*"strict TDD marker/config found → Use that value"*) y `:62` lo llama *"agent marker"*, sin decir qué es.

| Aspecto | Propuesta |
|---|---|
| Qué es | Una línea cuyo contenido entero es `Strict TDD Mode: enabled` o `Strict TDD Mode: disabled`. También vale la misma línea con el rótulo en negrita, `**Strict TDD Mode**: enabled`, que es como la escribe `sdd-init` en su reporte (`sdd-init/references/init-details.md:66`), para que lo que produce `sdd-init` cuente como marker. Cualquier otra forma no es un marker |
| Dónde vive | En las instrucciones que el CLI anfitrión carga en la sesión, las del proyecto o las de la persona. Nunca en un archivo que escribe Pegasus, porque reinstalar lo reemplaza entero. El contenido tampoco puede nombrar el archivo de instrucciones de un CLI concreto (`tests/test_content_core_is_cli_agnostic.py`): nombra la línea, no el archivo |
| Cómo se lee | Quien coordina la busca en las instrucciones que ya tiene en contexto, sin abrir archivos. Si hay una del proyecto y otra de la persona, gana la del proyecto; si dos se contradicen y no puede saber de dónde vino cada una, no hay marker, se pasa al flag del proyecto y se dice. `enabled` sin test runner queda inactivo, y se dice. La misma grafía viaja en el brief y reemplaza el `STRICT TDD MODE IS ACTIVE` de `sdd-verify/SKILL.md:43` |
| Sin `sdd-init` | Funciona igual: no depende de `openspec/config.yaml` ni de Engram, y sin marker ni flag rige el default por runner |

Lo que cuesta: ningún test de la suite puede probar que un agente note la línea, sólo que la regla está escrita, que es el mismo residuo que el de los routing facts. La línea vive en archivos que Pegasus no escribe, así que `doctor` no la informa y la persona la escribe a mano. Una línea en las instrucciones de la persona vale para todos sus proyectos, y la del proyecto es la forma de apagarlo en uno. La procedencia de una línea no siempre está a la vista del agente, así que dos líneas contradictorias degradan al flag. Y cambia un literal que hoy lee `sdd-verify`. Se descartaron dos alternativas: un archivo propio en cada proyecto, que es determinista y visible para `doctor` pero es una convención nueva que ninguna otra herramienta lee, y sólo `openspec/config.yaml`, que exige justo lo que el marker tiene que evitar: que `sdd-init` haya corrido.

**Cierre propio de (d):** `git grep -n 'STRICT TDD MODE IS ACTIVE' -- src` sale vacío y la regla vive en un solo archivo. La definición del marker se aprobó y entra en d2.

#### Cierre de cada slice

Además de lo propio de cada uno, un slice cierra cuando se cumplen cuatro cosas:

- la suite completa pasa: `PYTHONPATH=src:tests .venv/bin/python3 -m unittest discover -s tests -q` termina en `OK`, y el conteo se anota contra la base de 2892 más los tests que sumó el slice;
- `.venv/bin/python3 tools/check_docs_links.py` da PASS;
- una revisión independiente, en contexto fresco y con la consigna de romperlo, lo leyó antes del commit;
- y se commitea por unidad de trabajo: (a) en tres (a1-a4, a5-a6, a7), (b) en dos (b1-b5, b6), (c) en uno, y (d) en tres (d1-d4, d5, d6).

La fila del slice en la tabla de arriba pasa a llevar los commits y el conteo.

#### Riesgos del plan

| Riesgo | Mitigación |
|---|---|
| El cuerpo del orquestador se edita en (a) y en (c), y tiene 11 palabras de margen | a3 deja el cuerpo en 1400 palabras o menos; c2 es texto por texto; (d) no le agrega nada, porque el brief vive en el preflight y en el procedimiento |
| `king-pegasus.md` se edita en (a), (c) y (d) | El techo de a6 se mide con el margen de c3 y d5 escrito en su comentario; si no alcanza, el techo sube a propósito, nunca re-envolviendo líneas |
| `flow-applicability.md` se edita en (a) y en (b), y el corpus cita su texto literal | El techo de a6 reserva el lugar del puntero de b5, y toda edición de una cláusula citada lleva sus `decided_by` en el mismo commit: que la trazabilidad se rompa es lo que se busca |
| El renombre, el puntero y los tests de a3 separados en commits dejan un puntero colgado | Van en un solo commit: `test_skill_references` y `test_adapter_reference_integrity` fallan ante una referencia que no resuelve |
| `ftd-procedure.md` nace en (b) y se edita en (d) | (d) va después de (b); d5 depende de b3 |
| El texto de hoy contradice lo decidido: `sdd-applicability.md` pone como señales de SDD *"an approach worth arguing, trade-offs"*, *"across several sessions"* y *"a written record has to survive the session"*, y dos casos ambiguos mandan una decisión de diseño a SDD; `pegasus-orchestrator.md:35` dice que un record que sobrevive a la sesión es SDD | El renombre invierte esas señales en vez de conservarlas, y los tests de a3 fijan su ausencia |
| Poco margen en los especialistas: al explorer le quedan 99 palabras bajo 516 y al general unas 32 bajo 556 | Las frases de a7 y c4 son una o dos oraciones; si no entran, se sube el techo a propósito |

### Fuera de v7

Dos capacidades quedan para después, con su propio diseño y su propia aprobación. v7 sólo mapea dónde se enganchan:

- **Detección de brechas de skills o procedimientos.** Cuando el trabajo entregue o repita un procedimiento: si una skill o un agente ya lo cubre, se usa; si no, se registra la brecha y se **propone** una skill nueva, nunca se crea ni se instala sola. La señal es evidencia de repetición o de necesidad real, no coincidencia superficial de palabras; reutiliza el skill registry y `_shared/skill-resolver.md`, y no interrumpe un flujo activo.
- **Tooling operativo basado en evidencia.** Detectar integraciones reales del proyecto —dependencias, imports, configuraciones, variables de entorno— y sólo entonces proponer scripts, comandos o automatizaciones repetibles. Nada especulativo; nunca crear `.env` reales ni tocar credenciales; un artifact aprobado lleva como mínimo documentación, `.env.example` y un smoke test read-only; la ubicación project-local queda a evaluar.

**El pedido de "reportá una oportunidad de tooling" en cada brief queda fuera de v7.** No es mapear: cambia lo que el orquestador escribe en cada brief y lo que cada subagente devuelve, y agrega una lista de candidatos que nadie diseñó dónde vive, todo dentro del contexto que v7 está protegiendo. La materia prima ya existe sin tocar los briefs: `pegasus-verifier` devuelve *"each command as you ran it, its exit code"* (`pegasus-verifier.md:42`), `pegasus-implementer` devuelve *"the proof you ran and what it produced"* (`pegasus-implementer.md:38-39`), *Evidence* guarda comandos textuales y Engram guarda lo que pasó entre sesiones. Para el diseño futuro quedan como punto de partida: proponer en los cierres naturales —el fin de un FTD, el cierre de una sesión— y no a mitad de trabajo; la vía a pedido por la ruta consulta (*"¿qué tools le faltan a este proyecto?"*); dónde se acumulan los candidatos y con qué umbral de repetición; y si hace falta una línea fija en el cuerpo del implementer y del verifier para lo que sólo el subagente ve.

### Confirmaciones y lo que sigue pendiente

Los puntos 1 a 6 que la fase 2 dejó abiertos se confirmaron el 24 de septiembre de 2026 y viven en el cuerpo: el readiness de quien firma lo que escribió, en [Actores y readiness fuera de SDD](#actores-y-readiness-fuera-de-sdd); la consulta sin etiqueta, los nombres L0, FTD y SDD y FTD sólo por routing, en [Las cuatro rutas y los routing facts](#las-cuatro-rutas-y-los-routing-facts); un escritor por vez, en [El record FTD y dónde vive](#el-record-ftd-y-dónde-vive); y la compatibilidad, en [Compatibilidad, permisos y seguridad](#compatibilidad-permisos-y-seguridad). Los cuatro puntos que agregó la fase 3 se aprobaron el mismo día, y figuran abajo con su estado. Solo queda abierta la versión, que se decide al cortar la release.

| Punto | Estado |
|---|---|
| Definición del "agent marker" de Strict TDD | **Aprobada** el 24 de septiembre de 2026, tal como la define el plan del slice (d), incluida la variante con el rótulo en negrita |
| Prohibir secretos y contenido de archivos sensibles en *Evidence* | **Aprobada** el 24 de septiembre de 2026: tarea b4 |
| Dónde se nombra `ftd-procedure.md` | Sólo en la salida de la ruta FTD de `flow-applicability.md` (b5), porque al orquestador le quedan 11 palabras. Entrar a FTD pasa siempre por la escalera, aunque la ruta sea obvia: una lectura para decidir y una para ejecutar. Reescribe el criterio 7 aprobado en la fase 2, que decía «desde la capa de ejecución». **Aprobado** el 24 de septiembre de 2026 |
| Strict TDD en L0 | El orquestador lo resuelve una vez por sesión a través del preflight (SDD) y del procedimiento (FTD), no desde su cuerpo; en un L0 lo resuelve el implementer con la misma regla (d5). Reescribe el criterio 11 aprobado, que nombraba al orquestador entre los que referencian la regla. **Aprobado** el 24 de septiembre de 2026 |
| Versión mayor o menor | Una decisión de release, no de código. Antecedentes: 4.0.0 fue mayor por una ruptura explícita, 5.0.0 por cambiar el punto de entrada a un único ejecutable, 6.0.0 por soportar un segundo CLI (`7b8d4e7`), y de 5.1 a 5.8 hubo cambios de comportamiento que salieron como menores. Los identificadores de wire no cambian |

## Deudas sin unidad asignada

Trabajo conocido que no pertenece a ninguna unidad del corte. Se acarrea a propósito, y cada ítem declara qué lo destraba, para que el acarreo sea una decisión y no un olvido, y qué puede hacer una persona mientras siga abierto — vacío donde no hay nada útil que decir. Acá va sólo lo que todavía está por decidirse o por hacerse: lo que funciona así a propósito vive en [Limitaciones aceptadas](#limitaciones-aceptadas), más abajo.

| Deuda | Qué la destraba | Qué hacer mientras tanto |
|-------|-----------------|--------------------------|
| Un agente recibe `apply_patch` sin que Pegasus se la conceda nunca, y esto no tiene arreglo de código: el pliegue está verificado en dos lugares independientes del runtime, no uno. `packages/opencode/src/permission/index.ts` (`const edits = ["edit", "write", "apply_patch"]`) agrupa los tres bajo el permiso `edit` al decidir qué herramientas manda, y el comodín del mapa `tools` no lo alcanza porque ese filtro compara por clave exacta. Por separado, `packages/core/src/v1/config/agent.ts` (`normalize`) chequea el permiso declarado contra el literal `"patch"`, no `"apply_patch"` — así que `tools: { apply_patch: false }` no es un intento fallido, es un no-op silencioso: genera una clave `permission.apply_patch` que el runtime nunca consulta. Ningún hook de plugin puede sacar una herramienta de la lista de las que se mandan al modelo — se verificó leyendo la interfaz completa de hooks. Y aguas arriba ya se decidió no separarlo: el issue #40150 pedía esto mismo para `write` y se cerró con el PR #47352, que es sólo documentación y dice que el hilo convergió en que es un problema de documentación y no de código; el #18008 lo pedía para agentes de plan específicamente y se cerró sin fix. Así que todo agente al que este producto le concede `edit` o `write` recibe la herramienta y su descripción imperativa, «Use the `apply_patch` tool to edit files». La afirmación es la regla y no el conteo, que se lleva solo: hoy son **14 agentes**, y la cifra no se retipea acá sino que se deriva del árbol de contenido —los agentes cuyo mapa de herramientas renderizado enciende `edit` o `write`— en `ApplyPatchReachesEveryEditingAgentTest` (`tests/test_architecture_debt_figures.py`), que falla el día que deja de coincidir. Antes decía un número escrito en palabras, sin nada que lo comparara con nada, y quedó falso en silencio el día que `pegasus-implementer` se embarcó. No es escalada: escribe exactamente lo que `edit` ya permite. Lo que rompía era la lectura del render, que presentaba `"*": false` como si cerrara todo lo no nombrado. Ya costó una confusión real: un agente trató esa descripción como instrucción de mayor prioridad que el prompt de sistema y se negó a editar por SSH | **Ya se tomó la salida documental, y la corrección viaja además por el canal de la propia herramienta.** Los docstrings de `_tools` y `_permission` en `render.py` declaran el pliegue, explican por qué añadir `apply_patch` a `TOOL_NAME` o `PERMISSION_NAME` sería ese mismo no-op, y un guardián (`ApplyPatchPermissionFoldTest` en `tests/test_opencode_adapter.py`) fija que ninguna de las dos tablas nombra `apply_patch`, con mutación probada en ambas. La mitigación más fuerte, sin embargo, no es documental: el producto embarca `src/pegasus/adapters/opencode/assets/plugins/apply-patch-scope.ts`, que engancha `tool.definition` y le agrega un párrafo de alcance a la descripción de la propia herramienta, así que la corrección llega por el mismo canal que la frase que se leyó mal. Tenía que llegar por ahí: el texto que viaja con las definiciones de herramientas pesa más que el que viaja como prompt, y eso se aprendió de una negativa real que dos intentos del lado del prompt no alcanzaron a corregir. Enmienda una descripción; no saca una herramienta, así que lo que dice la columna de al lado sobre los hooks sigue entero. Su motivo y su límite están en el archivo y en «Enmendar el texto del runtime, no sólo agregar el propio»; acá sólo se lo nombra, y `ApplyPatchScopeIsCorrectedOnTheToolChannelTest` (`tests/test_architecture_debt_figures.py`) deriva del árbol cuál es el plugin que escribe esa descripción y exige que la fila lo nombre. La otra salida —pedirle al runtime que evalúe `apply_patch` por su propio nombre— no depende de este código: depende de que los mantenedores de OpenCode reabran una decisión que ya tomaron dos veces. Nada de esto cierra la deuda: la herramienta le sigue llegando a todo agente que pueda editar, y lo único que cambia es que ya no puede leerse mal desde adentro del producto | Si un agente cita la descripción de `apply_patch` para negarse a editar, decírselo en el pedido: el prompt compartido ya la nombra y no hay forma de sacarle la herramienta sin sacarle `edit` y `write` con ella. Y no leer el `"*": false` del render como si cerrara lo que no nombra — ya no hace falta inferirlo, el propio `render.py` lo dice |
| En un cliente ACP —Zed y similares— el `ask` de un sub-agente podría no llegar nunca a una persona y dejar la llamada colgada en vez de fallar limpio. El handler busca la sesión en un registro que sólo contiene las que creó el propio ciclo ACP, y la sesión hija que lanza la herramienta `task` no está ahí, así que retorna sin contestar ni allow ni reject: el `Deferred` queda pendiente sin timeout hasta que se destruya la instancia | Poder ejecutar OpenCode bajo un cliente ACP, que es lo único que lo confirma o lo descarta. Es análisis de fuente, no observación: quien lo leyó no pudo descartar que otro camino registre la sesión hija antes de que corra el handler. Mientras tanto está dicho en la documentación, que es lo honesto cuando se cambió una negativa dura por una pregunta sin poder probar todos los clientes | Bajo un cliente ACP, una llamada de sub-agente que queda colgada sin haber preguntado nada no se libera sola: hay que cortar la sesión. Bajo la TUI de OpenCode el camino no se recorre |
| No hay CI en el repositorio: `.github/` no existe. La estructura documentada describe `manifests/` como "generados, verificados en CI", y esa verificación no la corre nada | Nada técnico. **El 12 de septiembre de 2026 se decidió no incorporar CI por ahora, por lento y molesto.** Lo que ocupa su lugar no es el olvido sino dos prácticas que hoy se cumplen en cada cambio: toda modificación corre la suite completa —las más de dos mil— antes de darse por terminada, y todo trabajo pasa por una revisión adversarial en contexto fresco cuya única consigna es romperlo. La segunda es la que más rinde y la que menos respaldo tiene: en la jornada del 12 de septiembre los cuatro defectos más caros los encontró esa revisión y ninguno la suite, y sin embargo el paso no figura en `docs/release-distribution.md`. Escribirlo ahí dejó de faltar: `docs/release-distribution.md` abre ahora con los dos pasos y con el motivo por el que el segundo no es opcional | Antes de publicar, correr la suite completa a mano y seguir el procedimiento de `docs/release-distribution.md`, que es lo que hoy ocupa el lugar de la verificación automática |
| Las releases ya publicadas siguen llevando `skill-versiones-estandar-asi` dentro del artefacto, y con él la matriz de versiones homologadas de una organización. Son **51 tags** en un repositorio público —los anteriores a `fbbe94e`, el commit que los retiró del contenido el 2026-09-02—, más cada copia que alguien haya descargado. La cifra se mide con `git tag --no-contains fbbe94e` y no crece con las releases nuevas, que ya no lo llevan: decía 33 porque ese era el conteo el día que se escribió esta fila, y quedó vieja sin que nada avisara. Sacarlo de `main` no alcanza para deshacer eso | Una decisión sobre qué hacer con lo ya publicado, que es de quien administra el repositorio y no del código: no publicar nada, retirar los assets de las releases afectadas, o reescribir la historia. Cada opción tiene un costo distinto y ninguna es reversible. **El 12 de septiembre de 2026 quien administra el repositorio decidió no atacarla por ahora, sabiendo que el alcance sigue creciendo.** No es un olvido ni una deuda esperando su turno: es una postergación tomada con el costo a la vista, y sigue acá porque la decisión puede reabrirse, no porque falte tomarla | Quien haya descargado una release anterior a `fbbe94e` la tiene en disco: se borra la skill del directorio de skills instalado. Una instalación nueva ya no la trae |
| El orquestador delega de más, hasta cosas chicas que no lo justifican. Reportado por el usuario a partir de uso real, no de una lectura de código. Desde 7.5.0 una de sus causas posibles, la viñeta del umbral que manda a delegar toda ejecución de pruebas, tiene una excepción nombrada (la corrida única de la suite completa sobre el árbol integrado la hace el coordinador); el resto del texto no se tocó y la entrega en paralelo no se ofrece para trabajo chico | Que el usuario junte casos reales y los pase, para poder mirar qué texto los produce. La sospecha es un texto que empuja a un modelo literal a delegar — la misma clase de causa que la inundación de engram de 7.1.0 — pero no hay todavía un caso concreto para confirmarlo | Nada por ahora |
| Entrega en paralelo (7.5.0) medida sólo en parte. Diez riesgos (el procedimiento sigue siendo largo, y eso es una preocupación abierta): (1) en OpenCode, una llamada `edit`/`write` con ruta relativa se resuelve contra el checkout principal, no contra el worktree; (2) en OpenCode, los patrones del permiso `edit` son relativos al proyecto y un archivo externo produce `../..`, así que un permiso por ruta relativa no coincidiría; (los riesgos (1) y (2) no se observaron en la quinta corrida en vivo, 2026-10-02, en OpenCode: la verificación de aislamiento pasó; siguen abiertos porque no se midieron de forma adversaria); (3) en Claude Code, un hijo en segundo plano recibe un conjunto reducido de herramientas, sin MCP; (4) en Claude Code, no se midió si un `cd` de Bash a un directorio externo pide permiso; (5) el procedimiento se ejercitó en vivo en Claude Code `-p` (cuatro corridas) y en OpenCode (una corrida interactiva de la persona); después se midieron en vivo, con Claude Code, el conflicto de cherry-pick y la corrida interrumpida (sección «7.6.0»); sigue sin observarse el camino de una unidad lanzada que falla; (6) **resuelto en parte** (en OpenCode, un subagente de profundidad dos o mayor que dispare el `ask` queda esperando un aviso que ninguna vista muestra, #39112; a profundidad uno el aviso aparece en la sesión raíz según el código fuente, sin medir): un `git push` de un subagente ya pide confirmación en las dos CLIs (decisión de la persona, sección 7.5.0; evidencia en el código fuente de OpenCode y en la documentación de permisos de Claude Code, más los tests de render), y lo que sigue sin atraparse son alias, scripts propios, `sh -c`/`eval`, los `gh` con banderas globales antes del subcomando, `gh api -X POST` y `gh pr comment` (la ruta absoluta, el prefijo de entorno y los `gh` que escriben se cubrieron después), y los patrones con comodín preguntan también por cualquier git cuyos argumentos contengan «push» (los commits se protegen con `commit -F`), de modo que «nunca hacer push» sigue siendo además una instrucción; en Claude Code la confirmación también alcanza al coordinador; (7) en Claude Code Pegasus no renderiza ninguna regla de allow de Bash, de modo que cada comando de git y de pruebas del procedimiento cae al aviso por defecto salvo que la configuración propia de la persona lo permita, y la corrida en vivo del 2026-10-02 mostró que un `cd <dir> && git ...` se deniega (por eso el procedimiento usa `git -C` y nunca encadena `cd` con git); una medición del 2-10-2026 mostró además que `cd <dir> && <comando> > <archivo>` se deniega siempre, porque Claude Code no puede saber contra qué directorio se resuelve el destino de la redirección tras un `cd` en un compuesto, y que `--add-dir` no lo arregla (por eso el procedimiento nunca encadena `cd` con una redirección); (8) el modo fork interactivo de Claude Code vuelve a todo hijo un hijo en segundo plano, sin medir con este procedimiento; (9) el default propio del runtime para el trailer de commit puede agregar atribución, y lo que lo atrapa es la verificación del paso 12; (10) alcance: la segunda corrida en vivo (2026-10-02) mostró que el orquestador no llega al procedimiento a través del criterio; primer arreglo aplicado (puntero en el cuerpo siempre cargado); alcanzado y seguido, medido en la cuarta corrida en vivo (2026-10-02) bajo Claude Code `-p`; alcanzado y seguido también en OpenCode, medido en la quinta corrida en vivo (2026-10-02) | Correr una entrega real de dos unidades en cada CLI, con una ruta relativa de prueba, un `cd` externo y un hijo que pida una herramienta MCP, y mirar `git status --porcelain` del checkout principal | Las instrucciones del brief (ruta absoluta, comandos dentro del worktree, sin push) y la verificación de aislamiento del paso 7 son la única defensa; si el estado del checkout principal muestra algo que escribió una unidad, parar y avisar |
| OpenCode 2, **en espera** (decisión de la persona del 2 de octubre de 2026). Al 2026-10-02: `opencode-ai` latest es 1.18.34 y todas las releases «Latest» de GitHub son 1.18.x; v2 sale aparte como `@opencode/cli`, en 2.0.22, con 22 versiones en tres semanas desde el 11 de septiembre, y sin notas de release publicadas (#52184); el issue del propio equipo «V2 beta: isolate storage/database from stable OpenCode data» (#34831) sigue abierto, todos los canales resuelven a `opencode.db` y v2 le aplica sus migraciones; hubo regresiones entre parches (#52259, #52284); su binario también se llama `opencode`, así que tapa al 1.x en el PATH; no hay fecha anunciada | Retomar cuando ocurra cualquiera de estas: `opencode-ai` latest pasa a 2.x o la release «Latest» de GitHub es v2; se cierra #34831; aparecen notas de release de v2 | Nada. El relevamiento anterior de lo que v2 rompe (deudas de 7.3.0) sigue valiendo como mapa, pero hay que volver a verificarlo cuando se retome |
| El puerto de engram (7437) es compartido por todos los usuarios de la máquina: si el `engram serve` de uno lo ocupa, los hooks de Claude Code de otro (y el plugin de engram de OpenCode, que ya se comportaba así) mandan sus sesiones y prompts a la base del primero. Encontrado en la prueba en vivo de 7.7.0, que usó `ENGRAM_PORT=7438` para evitarlo | Aislar por usuario: un puerto propio por usuario, o comprobar quién es dueño del servidor antes de escribirle | Fijar `ENGRAM_PORT` a un puerto propio en cada usuario de una máquina compartida y comprobar con `engram stats` |
| Recuperación después de compactar bajo Claude Code: los hooks de 7.7.0 no cubren `compact` ni devuelven contexto a la sesión. Es el slice siguiente | Decidir qué se devuelve y cómo sin volver al protocolo inyectado de 7.1.0 | Pedirle al agente `mem_context` al retomar |
| playwright 0.0.83 está disponible y el contenido fija 0.0.79 (`tools/check_dependency_updates.py`, primera corrida real). Subirlo necesita integridad y lockfile nuevos | Leer el changelog de playwright antes de subir | Nada: la 0.0.79 sigue andando |
| El hook de engram de Claude Code no tiene el equivalente de `redactKnownValues` del plugin de OpenCode: tapa por catálogo, pero no los valores que la sesión ya conoce | Portar el mecanismo al script del hook | No pegar credenciales en prompts, que bajo Claude Code el modelo igual las ve |

### Deudas resueltas

Una deuda de la tabla de arriba puede cerrarse con código en vez de perder el sujeto: se anota acá, distinta de las disueltas, precisamente para no confundir las dos cosas.

| Deuda | Qué la resolvió |
|-------|------------------|
| Los chequeos de mundo cerrado de v7 sobre la escalera tienen como unidad el bloque —una lista o un párrafo—, así que una afirmación repartida en dos párrafos sueltos de una sección de decisión («Un record que sobrevive a la sesión sigue importando.» / «Justo ahí aplica SDD.») no la veía ningún chequeo, porque un escaneo de texto no sigue un argumento de un párrafo a otro. Estaba declarada como residuo junto a `SDD_MEETS_FTD_STEMS` en `tests/test_flow_routing.py` | `DECISION_PARAGRAPHS`, en el mismo archivo, cierra el hueco por mundo cerrado y sin leer el argumento: en *Decision order*, *The routes*, *Ambiguous cases* y *Promotions* de `flow-applicability.md`, los párrafos sueltos tienen que ser exactamente los fijados tal como están escritos —las frases de introducción y los dos párrafos que cierran una sección—, así que un párrafo nuevo falla diga lo que diga. Los ítems se leen como los lee una cita, marcador y continuación con sangría: una línea pegada a un ítem sin sangría cuenta como párrafo, y todo lo demás de esas secciones es una cláusula citada, que el corpus de routing rompe si se edita. `test_the_reviewers_two_paragraph_split_is_caught` planta en memoria el par de párrafos de la revisión, y el residuo junto a `SDD_MEETS_FTD_STEMS` ahora dice que el hueco está cerrado |
| `ftd-procedure.md` se lee en cada FTD y no tenía techo de palabras, y el slice (d) le iba a agregar la línea de Strict TDD | `FTD_PROCEDURE_WORD_CEILING = 915`, en `tests/test_orchestrator_routing.py`, con el mismo mecanismo y las mismas convenciones que los otros tres techos: cuenta el archivo entero, y su comentario dice lo medido después de d5 —915 palabras— y que no reserva nada, porque v7 no le agrega más. El archivo entra también en el loop de `WordCeilingIsReformatProofTest` |
| En *Roles y límites* de `docs/metodologia.md`, la fila «Quien coordina un FTD» ponía una obligación positiva en la columna *Límite importante*, donde las demás filas ponen un «No …» | La celda pasó a ser un límite sin perder la obligación: «No declara listo un cambio sin leer las observaciones registradas; si firma algo que escribió él mismo, no lo presenta como verificación independiente.» |
| Los chequeos de mundo cerrado de v7 que filtran por una lista de raíces tuvieron un hueco de vocabulario en cada slice: *handoff*, *private key* y *API key*, *shippable*, *skip TDD* y *always write tests before code*. Cada vez se amplió la lista después de que una revisión lo encontrara | `tests/fixtures/closed-world-vocabulary.json` guarda, por tema, frases naturales que cada lista tiene que reconocer —cada frase que una revisión encontró faltante y los sinónimos obvios del registro—, y `tests/test_closed_world_vocabulary.py` las prueba contra las constantes reales, importadas y nunca retipeadas. Qué listas necesitan tema no se escribe a mano: se deriva leyendo el código de los tests que declaran un chequeo de mundo cerrado, y una lista sin tema falla. La primera corrida encontró 210 frases sin reconocer, repartidas en 18 de las 19 expresiones que el corpus nombra —entre ellas *choice*, que `_CHOICE_STEM` no veía, y «spec» y el contrato revisable, que `_SDD` no reconocía como SDD—. Ampliarlas obligó a fijar tres frases que ya existían: la cláusula de la ruta FTD en `SDD_MEETS_FTD_STEMS`, y el paso del flag del proyecto y la línea del hard gate en `CRAFT_RULE_SENTENCES`. De paso, la copia retipeada de `AUTHORITY_CLAIM` en `tests/test_phase_less_specialists.py` se cambió por la importación del original, porque la guarda la vio divergir |
| `README.md` contaba el flujo anterior a v7: «primero entender, después especificar…» como la versión corta, y `sdd-verify` como autoridad final de readiness para cualquier cambio ejecutable o de configuración | Antes de la release de 7.0.0, *Cómo encaja el flujo* pasó a contar las cuatro rutas, FTD como carril habitual y SDD sólo con un contrato revisable, y acota `sdd-verify` a archivar un cambio SDD: fuera de SDD, el listo lo declara quien pidió el trabajo |
| Un `append` renombrado se perdía por una corrida, y `doctor` no lo veía | Renombrar sólo el `id` de un `append` dejando el valor idéntico hacía que `install` lo tratara como colisión ajena, lo salteara, y después retirara el registro viejo: el ítem desaparecía del documento entero y volvía recién en la corrida siguiente. Reproducido de punta a punta antes de tocar nada —`/plugin` pasaba a `None`— y confirmado que en esa ventana `doctor` no reportaba nada: decía «102 artifacts installed» en vez de 103, sin drift ni missing. El agujero estaba **por duplicado**: en `planner.py`, que decide, y en `cli.py::_merged`, que escribe el journal; `_merged` ya tenía un comentario advirtiendo que duplicar el chequeo haría divergir las dos versiones, y habían divergido. La exclusión de `record_address` no se tocó —sigue siendo correcta: el pointer nombra la lista, no un ítem, y darle dirección a un `append` haría que Pegasus reclamara los ítems de la persona—. Lo que se agregó es `record_append_identity`, hermana pública suya, que reconoce por huella `(target, pointer, after_digest)` y se consulta **sólo** después de que fallan el `id` y la dirección. Una revisión adversarial reportó que el cambio permitiría adoptar y borrar un renglón escrito a mano: se verificó corriendo el mismo escenario contra el árbol con el arreglo y contra `HEAD` sin él, y el resultado es idéntico en los dos — ese borrado es la limitación aceptada de localizar un `append` por huella, no algo que este cambio introduzca. Con el arreglo el renglón de la persona sobrevive y el de Pegasus también |
| El vocabulario de placeholders declaraba siete nombres y el render de un cuerpo contestaba uno. `core/placeholders.py` afirmaba que agregar un nombre obligaba a todo adapter a contestarlo, y `content` validaba los cuerpos contra la lista entera, mientras `render._body` sólo contestaba `skills_root`: un autor que escribiera `{{program_name}}` en el cuerpo de un agente pasaba la validación de contenido y hacía fallar el **install**, dos comandos después de la equivocación | Se partió el vocabulario en dos, que es lo que pedía la asimetría real y no una decisión nueva: seis de los siete nombres sólo tenían consumidores en `adapters/opencode/assets/` y `skills_root` sólo en `content/`, así que la partición ya existía de hecho y lo único que faltaba era declararla. `BODY_NAMES` gobierna los cuerpos y `ASSET_NAMES` los assets del adapter; `_asset_facts` conserva su acceso a los dos, porque angostar el lado de los assets no compraba nada. El error pasó a aparecer donde se comete: escribir `{{program_name}}` en un cuerpo falla **al cargar el contenido**, nombrando qué puede usar un cuerpo y dónde viven los otros. Lo que cierra la deuda no es la partición sino el espejo que la acompaña: un guardián deriva los dos conjuntos de las claves que `render.facts` y `_asset_facts` **realmente contestan** y exige igualdad de conjuntos, no inclusión, así que tanto agregar un nombre sin contestarlo como dejar de contestar uno declarado rompen un test. Sin esa mitad, partir el vocabulario sólo habría bajado el mismo defecto un escalón |
| Ningún front matter del contenido tenía vocabulario cerrado. En un descriptor de MCP, `_refuse_foreign_form_fields` rechazaba únicamente una clave que perteneciera al formulario de *otra* distribución, así que una clave que no pertenece a ninguno —`witheld_tools` en vez de `withheld_tools`— cargaba limpio, el campo real quedaba en su default vacío y el servidor no retenía nada mientras el front matter aparentaba que sí. El registro lo anotaba como un problema de MCP y eso era falso: agentes, skills y comandos ignoraban igual cualquier clave inventada | `_refuse_unknown_fields` cierra el vocabulario de **todos** los tipos con front matter, cada uno con el suyo declarado, y corre siempre después del chequeo específico para que un mensaje más nítido —«esto pertenece a otra forma»— gane cuando aplica. El vocabulario de un descriptor es la unión de los campos comunes con los de su forma, y `argv` quedó afuera de los comunes porque un `remote` no arranca nada, que era lo que el docstring ya decía y el código ya hacía. El alcance tuvo que ampliarse dos veces y la segunda la encontró una revisión adversarial, no la suite: la primera pasada cubrió MCP, agentes, skills y comandos, y dejó afuera las secciones de MCP del prompt de sistema, las secciones por agente y el propio `AGENTS.md`, que leen el front matter y lo descartan. Los tres tienen ahora vocabulario propio, y dos de ellos lo tienen **vacío**, que es la respuesta medida y no una que falte: derivan todo del nombre del archivo. El mensaje lo dice con esas palabras en vez de cortarse después de «valid fields are». Un recorrido exhaustivo del árbol confirmó que no queda ningún otro tipo con front matter sin cerrar |
| Nada exigía que un artefacto cuyo path se deriva de la identidad llevara el nombre en su `id`. El caso del prompt de sistema estaba cubierto por un test de migración puntual —su `id` era la constante `system-prompt`, así que un renombre le resultaba invisible al planner y el archivo anterior quedaba huérfano para siempre— pero no existía ninguna regla que lo generalizara | El conjunto de «artefactos cuyo path depende de la identidad» no se puede derivar leyendo el código: no hay un tipo ni un campo que lo marque, y una exploración concluyó por eso que no era derivable. Ejecutando sí lo es. `tests/test_identity_derived_ids.py` renderiza el catálogo completo bajo dos identidades distintas y compara: todo artefacto cuyo `path` cambia entre una y otra **es**, por definición, derivado de la identidad, y a ésos —hoy ocho, el prompt de sistema y los siete assets propios del adapter— se les exige que el `id` también haya cambiado. No hay ninguna lista escrita a mano, así que un artefacto nuevo con path derivado e `id` fijo rompe el guardián hasta que alguien decida qué significa. Empareja por posición y no por `id`, que es justo el campo que puede moverse, y por eso usa `catalog.render` y no las entradas ordenadas por `id`; afirma además que las dos corridas producen la misma cantidad, sin lo cual estaría comparando artefactos distintos en silencio. Devolver el `id` del prompt de sistema a la constante lo hace fallar, que es el defecto histórico exacto. Lo que **no** cubre sigue arriba: un append cuyo destino no depende de la identidad no entra en el conjunto observado |
| `test_tools_have_coverage` exigía que algún archivo de test **nombrara** cada script de `tools/`, no que lo ejercitara, así que un comentario lo satisfacía. Su docstring afirmaba que habría hecho imposible que `build_catalog.py` se rompiera en silencio, y en rigor sólo habría exigido que alguien escribiera ese nombre en alguna parte | El guardián pasó de buscar una cadena a recorrer el AST de cada archivo de test, y ahora sólo cuenta como cobertura un **import** del script o su nombre —literal, o por una variable de módulo— dentro de una llamada de la familia que ejecuta un proceso: `run`, `Popen`, `check_call`, `check_output`, y las cargas dinámicas `spec_from_file_location` e `import_module`. La llamada se reconoce por el nombre de la función y no por el módulo importado, para no romperse ante un `from subprocess import run`; y la búsqueda recorre toda la cadena de llamadas ancestras, sin lo cual el patrón real más frágil del árbol —`SCRIPT = ROOT / "tools" / "x.py"` leído como `str(SCRIPT)` adentro de `subprocess.run([...])`— habría quedado afuera. Los nueve scripts pasan sin necesitar un test nuevo ni una exclusión. Una primera versión cerró sólo la mitad: aceptaba el nombre dentro de **cualquier** llamada, así que un `print("x.py")` seguía alcanzando, y eso lo encontró una revisión adversarial y no la suite. Lo que queda afuera está nombrado en el docstring en vez de generalizado: el recorrido prueba que el nombre llega a los argumentos de una llamada de ejecución, no que esa llamada se invoque, así que un método auxiliar muerto daría cobertura. Atrapar eso pide instrumentar la ejecución, que es justo lo que un chequeo estático no hace |
| Las listas de inclusión aprobada de [docs/contrato-inclusion-artifacts.md](../contrato-inclusion-artifacts.md) se escribían y se actualizaban a mano, y ya se habían atrasado: el documento nombró tres servidores MCP mientras el contenido embarcaba cinco, y omitió dos plugins que se instalan, durante varios releases que igual se publicaron. El control de release exigía demostrar la coincidencia leyendo el mismo documento que habría que auditar | `tests/test_inclusion_contract.py` deriva del árbol los descriptores de `src/pegasus/content/mcp/`, los assets de `src/pegasus/adapters/opencode/assets/plugins/` y el mapa `_RENAMED_ASSETS` del adapter, y los compara contra la sección «Inclusión aprobada» **en las dos direcciones**: lo que está en el árbol tiene que estar nombrado, y lo que el documento nombra tiene que existir. La tercera comparación es la que no se ve venir y es la que más valor tiene: el documento describe qué plugin lleva prefijo y cuál conserva su nombre de origen, y esa verdad vive en `_RENAMED_ASSETS`, así que también se deriva — agregar ahí una entrada sin corregir la prosa falla. La extracción se acota a esa sección exacta y toma los literales entre backticks, y el modo de fallar importa: si el encabezado desaparece o se renombra, el test levanta en vez de comparar dos conjuntos vacíos, que es la forma que tendría este mismo guardián de volverse vacuo. Las skills se sumaron después, de la misma forma: `_skill_names` deriva de `src/pegasus/content/skills/` (excluyendo `_shared/`, que no es una skill invocable sino la biblioteca de fragmentos que las demás cargan) y se compara contra la sección en las dos direcciones. Para lograrlo la sección dejó de describir las skills por categoría y excepción ("todos los de contexto, excepto los que empiecen con `sergio-`") y pasó a enumerarlas por nombre: una regla categórica no tiene cómo compararse contra el árbol sin que el test reimplemente la categoría a mano, que es el mismo mantenimiento sin control que este guardián existe para cerrar |
| Una distribución no puede embarcar un servidor MCP propio. El overlay de `build_darq.py` es genérico sobre todo el árbol de contenido, así que agregar `content/mcp/<id>.md` y `content/agents/mcp/<id>.md` es trivial; lo que no lo es, es llegar a un agente. `optional_mcp` vive en el front matter **del agente**, y el overlay reemplaza por ruta en vez de parchear, así que una distribución tendría que embarcar copias completas de los ocho archivos de agente ya rebrandeados — exactamente lo que el contrato de inclusión prohíbe, y algo que se pudre en silencio en cuanto el motor edite el cuerpo de uno de ellos. Las skills no tienen este problema porque una skill es autocontenida y nadie la nombra desde otro archivo: `laravel-security` y `estandar-versiones-asi` ya viven sólo en DARQ | Se invirtió la dirección de la declaración: el descriptor nombra en `reaches` los agentes que alcanza, y `Agent.optional_mcp` pasó a ser **derivado** — la inversa de esas listas, calculada una vez en `_load_agents` y ordenada por id de servidor, que es exactamente lo que producía el front matter alfabético. Aguas abajo no cambió nada: `select_mcp`, `_denied_mcp_tools`, la resolución de `mcp_sections` y todo el adapter siguen leyendo `optional_mcp` igual que antes, y el catálogo completo con los cinco servidores elegidos da entrada por entrada el mismo digest que antes del cambio. Agregar un servidor es ahora **agregar archivos y nunca editarlos**. Las tres invariantes se reescribieron en la otra dirección y no se aflojó ninguna: `_require_known_optional_mcp` pasó a ser `_require_reaches_known_agents` — el error que atrapa cambió de forma y por eso cambió su relato, porque un nombre mal escrito en `reaches` ya no puede producir un permiso fantasma sino algo más callado, un servidor que llega a un agente menos del que su autor escribió, y ningún otro archivo del árbol se ve distinto por eso; `_require_mcp_reaches_an_agent` sigue existiendo pero quedó casi pegado a la declaración, `reaches` vacío y nada más, lo que además es lo que hace que el campo sea *obligatorio* (ausente y vacío llegan iguales al parser), y perdió la indulgencia para un árbol sin agentes porque ya no los lee; `_require_mcp_convention_referenced` conserva su lógica y cambió sus dos mensajes, que hablaban de un `optional_mcp` que el agente ya no declara, para mandar al autor al archivo que de verdad tiene que editar — y acá conviene ser más preciso que «no se aflojó ninguna»: esa tercera ya era blanda antes de la inversión y quedó exactamente igual de blanda. Ningún cuerpo de agente embarcado referencia una convención —un test lo prohíbe—, así que sobre el contenido embarcado el conjunto referenciado sale entero de las secciones, y las secciones salen del grant: lo único que la invariante exige ahí es que cada sección lleve su propio puntero. Las dos direcciones siguen disparando sobre un árbol que escriba el puntero en el cuerpo, y ambas se comprobaron construyéndolas, pero la inversión ni causó ni reparó esa blandura. Y la dirección vieja no puede convivir con la nueva: un archivo de agente que todavía lleve `optional_mcp` se rechaza al cargar, con el nombre del archivo y adónde se mudó la clave. Lo que esto **no** hace: no verifica el lado de la distribución. Habilita el camino — DARQ puede embarcar su propio servidor con `content/mcp/<id>.md`, su convención y su sección de agente, sin copiar un solo archivo del motor — y deja un residuo que conviene tener escrito: `reaches` nombra agentes **por nombre**, y una distribución rebrandeada renombra agentes, así que la lista tiene que nombrar los nombres *posteriores* al rebrandeo, no los del motor. Eso ya se ve en el árbol: el escenario de renombre de `test_distribution_e2e` tuvo que empezar a reescribir los `reaches` de los descriptores además de mover el override `<id>@<agente>.md`, que es el mismo acoplamiento por nombre que ese archivo ya tenía. Que el overlay de `build_darq.py` alcance para embarcar un servidor propio de punta a punta no está probado acá |
| El orquestador tenía el umbral de trabajo directo pero no las herramientas para ejercerlo: declaraba `[cbm, engram]`, así que podía resolver por su cuenta un cambio chico y ya entendido y quedarse sin la documentación de la biblioteca que estaba tocando, o sin poder ver la página que acababa de cambiar | Suma `context7` y `playwright`, y queda en el mismo conjunto que los cuatro agentes que sí manejan un navegador por oficio. Es la otra mitad de la decisión que le dio el umbral: un agente que puede resolver necesita lo mismo que cualquiera que resuelva. Lleva las secciones **compartidas** de los dos y no overrides, porque su encuadre propio es sobre el grafo — por eso tiene `cbm@pegasus-orchestrator.md` — y no hay nada particular que decirle sobre documentación ni sobre un navegador. Lo que esto le cuesta al guardián de playwright es lo interesante: ese test existe para que ampliar el alcance de un navegador obligue a escribir por qué, y pasó de sostener dos razones a sostener **tres** — cuatro agentes por oficio, `king-pegasus` por herencia de la reconversión, y el orquestador por el umbral, que no es ninguna de las dos anteriores. Los otros siete agentes angostados quedan afuera a propósito: propuesta, spec, tareas, init y archivo producen artefactos de texto, y un navegador no les sirve |
| El retiro saca archivos y deja los directorios que quedaron sin contenido. `_retire_files` borra cada `target` y nada más, así que retirar una skill entera —un directorio con archivos adentro— deja el esqueleto en pie. Medido sobre un HOME descartable: `pegasus uninstall --cli opencode` informa «removed 99» y deja **43 directorios vacíos**, incluidos `skills/`, `prompts/`, `commands/`, `plugins/` y `registry/`. No es inocuo: el registry que recorre `skills/` encuentra un `skills/<nombre>/references/` vacío y lo ve como una skill instalada. Está así desde siempre y se hizo visible en 5.9.0, la primera vez que Pegasus retira una skill completa | Lo que faltaba no era la regla sino cómo ejercerla sin poder destruir de más, y son dos cosas distintas. `remove_empty_dir` es `os.rmdir` y nada más: el vaciado lo decide el kernel **en la misma llamada que borra**, así que no hay ventana entre comprobar y actuar — el intento que se sacó de 5.26.0 tenía esa ventana, un `if` de «está vacío» alrededor de `shutil.rmtree`, y además la herramienta equivocada, porque `remove_dir` es recursivo por contrato y existe para que la retención borre carpetas de generación enteras. Que un directorio no esté vacío no es una falla sino la condición normal de parada, así que se informa por valor de retorno y no por excepción: mandarlo por el camino de los errores habría hecho ruidoso el caso corriente. `is_symlink` cierra la otra mitad. Antes de tocar un candidato se exige que **cada componente entre la raíz y él sea un directorio real**, preguntado sin resolver nada, porque `os.rmdir` resuelve todos los componentes menos el último: un `skills/` que sea symlink lo manda a borrar afuera del árbol, y ahí el syscall solo no alcanza — ése era el escape confirmado. Al symlink de la cadena se lo deja en pie en vez de desligarlo: es estructura de la persona, no del producto, y no está vacío. La poda corre una sola vez después de los tres handlers, porque un árbol de dependencias retirado también deja un padre vacío; asciende hasta el primer directorio ocupado; nunca toca el `config_dir`, por vacío que quede; y se reporta en `Retired.pruned`, sin lo cual nadie podría saber que ocurrió — el reporte de `uninstall` lo muestra, y el de `install`/`update` también, que era donde una revisión encontró que faltaba. El espejo es derivado y no enumerado: después de retirar un install completo no queda ningún directorio vacío bajo el `config_dir`, medido recorriendo el disco real, así que un handler de retiro nuevo que borre archivos sin alimentar la poda falla hasta que alguien decida qué significa. Escenarios contra un HOME descartable real, y los guardianes probados por mutación: desactivar la poda tira once, desactivar la contención de symlinks tira exactamente el del escape, ignorar el registro de directorios creados tira cuatro. Y lo que esto **no** alcanza está en la tabla de arriba: una instalación anterior a 5.28.0 no registró nada, así que no poda nada, y no hay curación automática posible sin adivinar de quién es cada directorio |
| Los nombres de artefactos on-disk llevaban la marca del motor fija en el código — `pegasus-AGENTS.md`, el subárbol `pegasus/skill-registry` con su binario y su módulo, el contrato `.env`, los tres plugins `.ts` con sus símbolos exportados y el paquete npm del notifier —, así que una distribución rebrandeada mostraba «Pegasus» en el disco de una instalación que no se llama así, y en un toast que la persona lee | La causa no era una lista de literales: **el adapter nunca recibía la identidad**. `cli.py` la tenía en `Runtime` y moría ahí, y `core/catalog.py` llamaba a `own_artifacts` con un nombre de orquestador y nada más, así que no había dónde poner la derivación. Se hizo en dos mitades a propósito, para que una falla dijera cuál de las dos la causó: primero la plomería — `Identity` viaja explícita y **obligatoria** hasta `own_artifacts`, sin default, con un guardián que exige `TypeError` si alguien la omite y otro que escanea el adapter para confirmar que no se la busca por su cuenta — y recién después la derivación. Los nombres salen de `program_name` en cuatro formas (`adapters/opencode/naming.py`: tal cual, con guiones bajos para el módulo, PascalCase para el símbolo exportado, y en minúsculas para npm, que rechaza de plano una mayúscula en el nombre de un paquete), y lo que va **adentro** de un asset entra por el mecanismo que ya existía, `placeholders.fill`, no por uno nuevo. Los archivos fuente perdieron la marca — `skill-registry.ts`, `zellij-state.ts`, `skill_registry.py` — y el nombre instalado se deriva, así que el repositorio dejó de fijar lo que la distribución decide. El espejo estaba escrito como exclusión y esa frase **era** la deuda: `test_cli_identity_sweep` declaraba en su docstring que los nombres de archivo quedaban «fuera de alcance aquí»; ahora recorre lo efectivamente instalado. Y un defecto que sólo apareció al probar la migración en vez de asumirla: el `id` del prompt de sistema era la constante `system-prompt`, así que un renombre le resultaba **invisible** al planner — el `id` no cambiaba, la entrada vieja nunca entraba en `retirements`, y el archivo anterior quedaba huérfano para siempre. Pasó a ser `system-prompt:<nombre>`, la misma forma que ya usaban el registry y los plugins. Lo que se decidió **no** derivar queda anotado como deuda propia más arriba |
| `pegasus_version` en el journal lo escribía sólo `empty()`, así que después del primer install el campo quedaba congelado en la versión que corrió ese día y ningún upgrade posterior lo movía | El store lo estampa en cada escritura con la versión corriente, que ya recibe por constructor. El campo pasa a significar «la versión que escribió esto por última vez», que es el dato de procedencia que sirve en un diagnóstico, y no «la que lo creó», que no le servía a nadie. Va en el store y no en el core porque la versión corriente es un hecho del binario que escribe, no del journal como estructura; y va antes de `_serialize`, que revalida round-trippeando por el parser del core, para que lo que se valida sea exactamente lo que va a disco. La clave del formato de cable no se toca: está fijada como identificador estable en toda distribución. Conviene ser preciso sobre qué NO era esto, porque el registro original lo exageraba: `doctor` nunca leyó este campo — reporta `runtime.identity.version` y hay un test que lo fija —, así que no había ningún dato incorrecto llegando a una persona, sólo un campo de procedencia que mentía sin que nadie lo consultara |
| La voz que existe para explicar no podía buscar: `king-pegasus` declaraba `[read, write, edit, skill, ask]` — sin `bash`, sin `grep`, sin `glob` — así que o pedía que le pasaran el archivo o explicaba sobre lo que alcanzara a leer. Y su cuerpo le prohibía verificar lo que acababa de escribir, cuatro líneas después de pedirle que lo escribiera | Reconversión, no ampliación de permisos: lo que limita a esa voz pasa a ser una obligación que lleva su prompt, y no un recorte de herramientas. `content/agents/king-pegasus.md` declara el mismo alcance que el orquestador (`read, write, edit, bash, grep, glob, skill, ask`) y los cuatro servidores MCP que el release embarca, y cambia `Never build after changes` por dos reglas: `Work out loud or not at all` y `Close the loop you open`. La diferencia es de naturaleza y no de grado: trabajar en silencio no es una herramienta que un permiso pueda denegar, así que esa disciplina sólo puede vivir en el prompt — el permiso dice *puede*. Las invariantes nuevas son derivadas: `set(requires_tools)` igual al del orquestador, y `set(optional_mcp)` igual al conjunto de servidores embarcados leído del árbol de contenido, así que agregarle una herramienta al orquestador o embarcar un quinto MCP falla hasta que alguien decida qué significa para esta voz. Se fueron además `GDE & MVP` y `LazyVim, Tmux, Zellij`: credenciales de terceros y preferencias personales de una persona, en contenido que se distribuye rebrandeado a una institución pública |
| El digest de un árbol de dependencias es la identidad de lo que se materializó y no un hash de lo que quedó en disco, así que `doctor` no podía detectar un árbol corrompido ni manipulado | El razonamiento original se sostiene y no se tocó: hashear el árbol necesita una lectura recursiva, barata para un binario y prohibitiva para un `node_modules` de decenas de miles de archivos. Lo que se verifica es más chico y es el que importa: **el único archivo que la configuración manda ejecutar**. `materialize` y `materialize_npm` registran su ruta relativa y su digest, y `doctor` lo relee — una lectura, no un recorrido. Prueba exactamente una cosa, que el programa que Pegasus colocó sigue siendo el que colocó, y no prueba nada del resto del árbol: una dependencia sustituida tres niveles adentro de `node_modules` le es invisible a propósito, porque atraparla costaría el recorrido que esto existe para evitar. Un registro anterior a este par no carga ninguno de los dos campos, y ahí no se afirma nada en ninguna dirección: se informa sin drift, que es lo único honesto cuando nunca hubo con qué comparar, **y se nombra en `unverified`**, porque «sin drift» y «nunca se chequeó» leídos igual serían la misma clase de silencio que esto vino a sacar. Lo mismo cubre el caso en que `npm ci` no dejó el script de entrada donde el descriptor dice. Ese resto no se cura reinstalando, porque un árbol ya materializado en la versión que el release pide se reutiliza sin tocar: se cura la primera vez que el descriptor cambia la versión de ese servidor. Y la ruta del programa se valida al cargar el journal —ni absoluta ni con `..`—, porque el lector la empalma sobre la raíz del árbol y un empalme no es un límite: una ruta absoluta descarta la raíz entera, y ahí el chequeo pasaría para siempre contra un digest que eligió quien editó el journal, sin leer el árbol real ni una vez |
| `mode_of` colapsaba «la ruta no existe» y «no pude leer sus bits» en el mismo `None`, con un llamador cuyo default es correcto para lo primero y equivocado para lo segundo: un archivo del usuario en `0600` devuelto como `0644` | El mismo tratamiento que la unidad 10 le dio a `exists`, por el mismo motivo: `None` pasa a significar ausente y nada más, y un camino que existe pero no se puede leer levanta `FileSystemError`. La otra mitad ya se había cerrado sola por refactor — `_write_back` omite el argumento en vez de elegir un default que no le toca, así que el `else 0o644` que la unidad 11 cita ya no estaba en el árbol. Que la suite entera pase sin tocar un solo llamador confirma lo que esa unidad había medido: `mode_of` corre siempre justo después de una lectura que ya tuvo éxito, así que la condición era inalcanzable. Se arregla igual, porque «inalcanzable hoy» es una propiedad de los llamadores de hoy |
| Los servidores atados se reportaban sólo bajo `doctor --start-mcp-servers`, un flag que existe para autorizar la ejecución de procesos, y ese chequeo no arranca ninguno: es una lectura pura del journal. Un `doctor` pelado no decía nada de ellos | Salen del flag. La disyuntiva anotada era meterlos en `mcp_servers` —que está documentado como el resultado de los lanzamientos y quedaría con entradas que nadie lanzó— o darles lugar propio; se eligió lo segundo, `mcp_bound`, que además hace explícito lo que son: servidores que la instalación concede y no instala. Dejarlos adentro del flag repetía, para la invocación que casi todo el mundo tipea, el mismo silencio que ese flag se había arreglado para sacar |
| Adoptar un artefacto que ya existía descartaba en silencio los permisos que la persona le hubiera agregado a mano | Decisión: **gana el producto**, que es la misma que la unidad 9 ya había tomado para los archivos cuando retiró el digest como permiso — lo que el journal reclama se reescribe sin preguntar. No era una decisión nueva sino una que faltaba escribir. Lo que sí faltaba de verdad era la otra mitad, que la política nunca abordó: si la persona se entera. El silencio nunca fue la decisión, sólo la forma más barata de implementarla. `Plan.overwritten` nombra ahora las actualizaciones que caen sobre una edición ajena, y no cuesta un solo acceso a disco: decidir `UNCHANGED` contra `UPDATE` ya obligaba a leer la dirección, así que el paso carga lo que encontró ahí, y que eso discrepe del digest registrado es la definición de una edición a mano. Se reporta en el install y también en el `--dry-run`, donde llega a tiempo para que alguien cambie de idea. Los `append` quedan afuera a propósito: se los localiza *por* el digest registrado, así que un valor que discrepa no se encuentra, y «alguien editó el nuestro» no se distingue de «alguien borró el nuestro y agregó el suyo» |
| `skill-versiones-estandar-asi` codificaba el estándar de tecnología interno de una organización —con su matriz de versiones homologadas— y viajaba en el contenido embarcado desde la mudanza de v3, sin que nadie decidiera publicarlo. `laravel-security` llegó por la misma mudanza | Los dos salieron del contenido. Ninguno era guía genérica, ningún comando ni agente los invocaba, y `docs/contrato-inclusion-artifacts.md` los nombraba como incluidos: ahora dice por qué no lo están. Lo que esto **no** deshace queda anotado como deuda propia más arriba — sacarlos de `main` detiene los releases futuros y no toca los publicados |
| El comodín con el que se conceden las herramientas de un servidor MCP alcanzaba también las que destruyen estado, porque su granularidad es el servidor y no la herramienta | Un descriptor nombra ahora, por excepción, lo que el comodín no debe alcanzar: `withheld_tools`. El comodín sigue existiendo para no obligar a enumerar todo lo que un servidor expone, y esto nombra sólo lo que tiene que quedar afuera. `select_mcp` resuelve esos nombres contra la clave que el agente realmente recibió, así que atar un servidor produce `codebase-memory-mcp_delete_project` y no `cbm_delete_project` — denegar una herramienta que no existe no protege de nada. `index_repository` no entra, y la deuda se equivocaba al incluirlo: la convención de CBM lo prescribe como la reparación de un índice viejo o ausente, así que denegarlo rompería una regla que el producto mismo le da a sus agentes |
| `doctor --start-mcp-servers` no decía nada de un servidor atado. Peor: como un servidor atado no escribe clave `/mcp/<id>`, una instalación cuyos servidores están todos atados reportaba «No MCP servers configured» — no un hueco en el reporte sino una afirmación falsa sobre la máquina | Una entrada de convención sin clave de configuración al lado alcanza para decir la verdad en su lugar. Lo que no se afirma es más de lo que el journal sabe, y son dos cosas: a qué clave se lo ató, que nunca se registró; y que sea una atadura, porque `retire` recorre los tipos en orden alfabético —`config-key` antes que `file`— así que un uninstall que quitó la clave y falló en la convención deja exactamente esta forma. El reporte nombra las dos lecturas en vez de elegir una. Arrancarlo sigue fuera de alcance, y contrastar su versión sigue bloqueado por afuera: el `serverInfo` del handshake no es confiable, engram reporta `0.1.0` corriendo `1.20.0` |
| Un `refresh failed` del plugin del skill registry quedaba sólo en `console.error`, que no llega a nadie: el registry servía un inventario viejo o vacío y nada lo decía | El plugin encamina sus dos fallas por un solo `reportFailure`, que sigue escribiendo en `console.error` —el log de registro— y además muestra un toast por `client.tui.showToast`, con `warning` para el contrato ausente y `error` para la falla del generador. El toast es estrictamente best-effort y va en su propio `try/catch`: un cliente sin TUI, como `opencode run`, no tiene dónde mostrarlo, y que esa llamada falle es un desenlace ordinario y no una segunda falla que reportar. El guardián no mira la prosa: ubica el cuerpo del helper por balanceo de llaves y exige que todo `console.error` del archivo caiga adentro, así que una ruta de falla nueva no puede volver a limitarse al log |
| `install` decidía "already current" comparando lo deseado contra el disco mientras `doctor` reportaba drift comparando el disco contra el digest del journal, así que una edición a mano que acertara lo que una versión posterior renderiza dejaba drift permanente: no se escribía nada, el journal no se actualizaba, y cada corrida siguiente repetía la conclusión | Se decidió que la pregunta verdadera es la del disco, y que el journal tiene que alcanzarla sin escribir. Un paso `unchanged` ya carga las dos mitades de la respuesta —el digest de lo que se quiere y la entrada contra la que se lo juzgó—, así que `planner._reconciled` produce el registro que el journal debería haber tenido, sin tocar disco, y sólo para los pasos cuya entrada efectivamente discrepa. Viaja en `Applied.reconciled` y no en `Applied.records`, y esa separación es la corrección entera: `records` es lo que un rollback puede sacar, y una reconciliación es un artefacto que esta corrida nunca escribió — ofrecérsela a `unplace` borraría un archivo correcto para deshacer una escritura que no ocurrió. Tampoco entra en el reporte: nada se escribió, así que nada se cuenta como escrito |
| No había `pegasus --version`: la versión sólo salía de `pegasus doctor --json`, un comando de diagnóstico contestando una pregunta que no es de diagnóstico | `-V` / `--version` lo contesta el parser y nada más — no se abre un home, no se lee un journal, no se resuelve un adapter. El número es del binario y no de ninguna instalación suya, y una máquina con la instalación rota es exactamente donde tiene que seguir funcionando |
| Los sitios de `content.py` que lanzan `ContentError` no tenían un test de tabla que recorriera todos y afirmara que cada uno nombra una ruta real | `test_content:ContentErrorSitesTest` deriva el conjunto de un recorrido del AST de `content.py` en vez de una lista escrita a mano, con la clave `(función, ordinal)`: un `raise` nuevo rompe el test hasta que alguien lo cubra, que es la misma costumbre de los guardianes. Hoy son 44 sitios, y el número sube solo: cada `raise` nuevo entra por el recorrido del AST, no por una lista que alguien tenga que acordarse de tocar. Los 8 que no nombran una ruta llevan el motivo escrito y no una exclusión silenciosa, y son de dos clases: los inalcanzables —`content:split_frontmatter`, porque `frontmatter.parse` nunca devuelve algo que no sea un mapa sin haber levantado antes— y los que refutan un valor que eligió quien llama y no un archivo, como los tres de `content:parse_mcp_choice` y el de `content:select_mcp`, donde no hay ruta que nombrar porque no hay archivo. La aserción es simétrica en las dos direcciones —un resultado sin ruta tiene que declarar por qué, y un motivo sólo se acepta en un resultado sin ruta—, así que nadie puede acallar un sitio agregándole una excusa. Y un tercer caso repite un subconjunto de los mismos árboles malformados **desde adentro de un zip real**, para que los fixtures no puedan estar esquivando el camino por el que producción lee su contenido |
| El orquestador tenía prohibición absoluta de ejecutar —prosa y `requires_tools` de acuerdo en no concederle nunca `write` ni `edit`— sin ningún umbral que le permitiera resolver algo por su cuenta | Decisión de producto, no corrección de un defecto: se le da al orquestador el mismo criterio de coordinación que ya rige a quien lo dirige a él —¿la acción infla contexto sin necesidad?—, con un umbral concreto (leer hasta 3 archivos o escribir uno solo, mecánico, se hace directo; leer 4 o más, o tocar 2 o más archivos no triviales, se delega entero). `content/agents/pegasus-orchestrator.md:Direct Work Threshold` traduce ese criterio a su propia voz y le agrega `write` y `edit` a `requires_tools`, así que ahora puede aplicar un cambio chico y ya entendido sin abrir una delegación para eso, pero sigue delegando todo lo que cruce el umbral |
| La voz `king-pegasus` explicaba y no podía aplicar nada de lo que explicaba: declaraba sólo `read` y su cuerpo le prohibía generar cualquier artefacto | Decisión de producto: esta voz pasa a poder aplicar el cambio que acaba de explicar, en vez de dejarle al usuario transcribir la explicación a mano. `content/agents/king-pegasus.md` suma `write` y `edit` a `requires_tools` y reescribe la premisa de apertura y la sección de comportamiento para que aplicar un cambio narre el porqué antes y durante, nunca en silencio como un agente implementador; lo que se preserva a propósito es esa voz que enseña mientras actúa, no la ausencia de acción. En ese momento siguió sin `bash`, porque la regla "Never build after changes" se mantenía: aplicar terminaba en la edición y nunca en correr nada. Eso lo revirtió después la reconversión de esta misma voz, más abajo en esta tabla |
| `restore` no podía devolver un árbol de dependencias: el snapshot excluía esos destinos enteros porque `capture_paths` lee bytes y un árbol es un directorio, así que un install que materializó una dependencia y falló no la deshacía | El alcance que se cerró es más angosto que el que la deuda nombraba, y a propósito: no hace falta que el snapshot sepa leer un árbol entero para que `restore` pueda quitarlo. `cli._prospective_dependency_targets` nombra, antes de que `_materialize_dependencies` escriba nada, la dirección donde un árbol nuevo va a aparecer; en ese instante todavía no tiene bytes, así que capturar "esto no existía" es el mismo caso que `capture_paths` ya resolvía para cualquier ruta ausente. `snapshot.Entry.is_directory` lleva esa marca al manifiesto —siempre con `existed=False`, nunca la claim de haber leído un árbol que ya estaba ahí— y `cli.restore` la lee para llamar `remove_dir` en vez de `remove`. Un árbol que ya existía antes de esta corrida —el caso que sigue pidiendo bytes que nadie captura— se queda exactamente donde estaba: afuera de todo snapshot, tal como hoy. Lo que se destrabó es el caso real detrás de la deuda —una materialización a medio camino, sin journal que la reclame— no la lectura de un directorio completo |
| El plugin de engram que se embarcaba estaba inerte —seis líneas— y su comentario afirmaba que «el MCP provee la integración». Eso era cierto sólo para el texto del protocolo, que un servidor MCP puede entregar por su campo de instrucciones; no era cierto para lo que un plugin anterior hacía y un MCP no puede: registrar `chat.message` (una vez por mensaje del usuario, antes de que el modelo lo vea), `tool.execute.after` (la captura pasiva, después de cada herramienta), los eventos de ciclo de vida de sesión, la supresión de sesiones de sub-agente, y hablar con un `engram serve` local | Se promovió a `assets/plugins/engram.ts` el plugin real de una instalación en uso —449 líneas, meses de producción—, con la única poda de referencias a un tracker de incidencias ajeno a este repo; las notas que explican por qué el código luce como luce se conservaron, reescritas sin el número que no significa nada acá. El plugin resultante registra `chat.message`, `tool.execute.after` (con captura pasiva de la salida de `Task`), los eventos `session.created`/`session.deleted` con supresión de sesión de sub-agente, `experimental.chat.system.transform` y `experimental.session.compacting`; resuelve puerto y binario por `ENGRAM_PORT`/`ENGRAM_BIN`, ambos con default sano y sin nada fijo a una máquina. `RealZipappShipsTheEngramPluginTest` en `test_opencode_adapter.py` arma un `zipapp` real desde este checkout, carga el adapter desde adentro del archivo y compara el contenido servido byte a byte contra la fuente — falla si el asset falta o llega degradado al empaquetarse |
| Ningún test arranca un servidor MCP. La suite verifica que el archivo se baje, que el hash coincida, que se extraiga, que el journal lo reclame y que la configuración quede escrita — todo cierto mientras el servidor no levanta. Es lo que dejó pasar que `engram` se instalara y no funcionara en 4.0.0 y 4.1.0, y lo encontró una instalación real y no la suite | `doctor` sumó `--start-mcp-servers`, apagado por defecto: la única forma en que deja de ser de sólo lectura. El framing JSON-RPC del `initialize` y la clasificación de la respuesta viven puros en `core.mcp_handshake` —no dependen de plataforma—; lanzar el proceso y garantizar que nunca sobreviva a la llamada queda detrás del puerto `ports.mcp_process:MCPProcess`, con `infra.mcp_process_subprocess:SubprocessMCPProcess` como única implementación real. `cli._mcp_entries` sólo deja pasar lo que el propio journal reclama como suyo —una entrada `config-key` cuyo id empieza con `mcp:`—, leído de la configuración que Pegasus mismo escribió; nada nombrado en otro lado es candidato. Un servidor configurado como remoto se informa como tal y no se arranca. Los veredictos son `ok`, `timeout`, `exited`, `invalid` y `not-found` desde el intercambio, más `remote`, `missing`, `invalid` y `unreadable` que se deciden antes de lanzar nada. Que sea flag y no comportamiento por defecto es la misma decisión que gobierna el resto de `doctor`: leer nada arriesga; ejecutar el comando que un cliente tiene configurado es un acto de otra naturaleza, y por eso hace falta pedirlo. Hay que ser preciso sobre qué prueba esto y qué no: prueba el camino de lanzamiento propio de Pegasus y el handshake, contra servidores fixture que viven en el árbol de tests —incluidos algunos que se portan mal a propósito—; no prueba que la suite hermética verifique `engram`, `cbm` o `playwright` reales, que sólo se ejercitan cuando una persona corre el flag en una máquina donde esos servidores están instalados — que es exactamente lo que hace un chequeo previo a publicar sobre una cuenta de prueba. Por eso la capacidad vive en el producto y no sólo en la suite: el mismo acto sirve a quien lo corre y sirve como verificación propia antes de publicar. De paso quedó una lección que generaliza: distinguir `exited` de `timeout` dependía al principio de ganar una carrera —un servidor que moría sin contestar podía reportarse como uno que nunca contestó—, un caso que apareció corriendo la prueba 40 veces y fallando una. Se resolvió dejando que el proceso asiente su salida después de que su stdout se cierra (`infra.mcp_process_subprocess:EXIT_SETTLE_SECONDS`), para que la clasificación deje de depender de qué lado gana |
| Un `granted_directories` inválido escrito a mano en el journal dejaba sin usar los nueve comandos que lo leen —`install`, `update`, `uninstall`, los tres de `mcp`, los dos de `directory` y `doctor`—, incluido el `directory revoke` con el que uno querría sacarlo. La validación al cargar era correcta y no se tocó: impide el replay de una escalación. Y tolerarla devolviendo el campo vacío **no** era la salida, aunque vacío fuera el estado más restrictivo: el campo se reescribe en cada guardado y un valor vacío se omite al serializar, así que «cargar vacío» se habría vuelto «borrado permanentemente en el próximo comando que toque el journal por cualquier motivo», en silencio | Se partió la entrada de la lista, no el fail-closed: `journal._granted_directories_from_dict` deja de rechazar el journal entero por una entrada inválida y en cambio la reparte — cada entrada que `content.validate_granted_directory` acepta va a `granted_directories`, exactamente como antes; cada una que rechaza va a un campo nuevo, `Install.quarantined_directories`, preservada tal como se leyó, de cualquier tipo JSON (`123`, `null`, un objeto), no sólo una cadena mal formada. La única forma que sigue siendo fatal es `granted_directories` no siendo una lista — ahí no hay estructura por elemento que preservar, y sigue lanzando `JournalError` igual que antes. La cuarentena no concede nada: ningún consumidor de `granted_directories` — el render de OpenCode, `directory grant`/`revoke`, `doctor`, `_merged` — lee jamás `quarantined_directories`, verificado corriendo el camino real de instalación con una entrada en cuarentena y comparando el conjunto efectivamente concedido, con mutación probada. `doctor` la nombra bajo `directories_quarantined` sin reclamarla, y `pegasus repair --cli <id>` es el comando nuevo que la saca: toma un snapshot del journal antes de escribir —así que `pegasus restore` lo deshace—, escribe una sola vez, y no toca nada más. «Tolerar como vacío» seguía rechazado, y por la misma razón que antes: `_merged` reconstruye el `Install` en cada corrida, así que un `install`/`update` común tiene que llevar la cuarentena hacia adelante sin tocarla — igual que ya hace con `granted_mcp`/`granted_directories` — o el mismo defecto de «vacío se escribe encima y se pierde para siempre» habría reaparecido con otro nombre |
| La poda de directorios no alcanzaba a ninguna instalación anterior a 5.28.0, y aunque `doctor` ya los nombraba desde 5.35.0, no había ningún acto que los sacara sin editar el disco a mano | El alcance que se cerró es acotado a propósito, y no es el que la fila original pedía: no es alcanzar la base instalada con una regla nueva de adopción — eso sigue siendo una decisión que no es del código, y las dos salidas conocidas (adoptar por contenido, o un acto explícito de la persona) siguen siendo las dos únicas, con la primera rechazada por la misma razón de siempre: no saber quién creó un directorio no es lo mismo que saber que no hay nada ajeno adentro, y confundir las dos reintroduce la ambigüedad que la poda vino a cerrar. Lo que se cerró es la segunda mitad, la del acto explícito: `pegasus repair --cli <id>` retira exactamente el conjunto que `doctor` ya nombraba bajo `unprunable_empty_directories` — `planner.remove_orphaned_empty_directories` reutiliza el mismo `planner.empty_directories_never_pruned` que `doctor` usa para descubrirlos, así que los dos no pueden nombrar conjuntos distintos —, revalidando la vacuidad y la cadena de symlinks en el momento mismo de borrar y no sólo al descubrir: un archivo plantado en la ventana entre el descubrimiento y el borrado salva el directorio, verificado sembrándolo así. `created_dirs` sigue sin curarse solo: sigue siendo sólo lo que una instalación efectivamente crea, tal cual documenta `Install.created_dirs`, y ningún `install`/`update` empieza a inferirlo. El punto ciego de symlink que la fila anterior admitía como "honesto pero menos útil" dejó de ser silencioso: `empty_directories_never_pruned` devuelve ahora `EmptyDirectoryScan(found, unwalkable)` en vez de una sola tupla, `doctor` nombra lo no recorrido bajo `directories_not_walked` -- tanto si es el propio `config_dir` como si es un subdirectorio encontrado a mitad del recorrido --, y `repair` lo carga en su propio reporte para que "reparado" no se lea como "no queda nada" sobre un subárbol que nunca se miró. Verificado con symlinks reales sobre disco real en ambos casos, con mutación probada en la reaparición de la vacuidad, en el límite de `config_dir` y en la propia visibilidad del symlink. Una revisión adversarial encontró dos defectos en `remove_orphaned_empty_directories` que la primera versión de este cierre no vio: el filtro de contención era léxico y no resolvía nada, así que un candidato con `..` en la ruta —`f"{config_dir}/../outside"`— pasaba el filtro y llegaba a un `os.rmdir` real que el kernel sí resuelve, borrando un directorio **fuera** de `config_dir`; reproducido de punta a punta antes de tocar nada, con el directorio ajeno efectivamente desaparecido. El arreglo es el mismo que `journal._contained` ya aplica y por la misma razón: refusar `..` por forma en vez de resolverlo, sin empezar a seguir symlinks que `_free_of_symlinks` ya rechaza. El segundo no era un defecto sino una cláusula muerta: `current != config_dir and config_dir in current.parents` llevaba una mitad que `Path.parents` ya volvía inalcanzable —nunca contiene la propia ruta—, y dos tests escritos para esa frontera pasaban igual sin ella, que es la señal de que no hacía nada. Se sacó, y el test que de verdad prueba el límite quedó documentado como tal en su propio docstring, con la cláusula que sí sostiene el límite (`config_dir in current.parents`) probada por mutación |
| La pantalla de elección de servidores MCP de la TUI se describía a sí misma como el default seguro y no lo era para una instalación con servidores **atados**. `McpSelectionScreen.chosen` arrancaba con lo que el journal registra como **instalado**, y su docstring afirmaba que dejar cada fila como se la encontró e ir a Continue «reproduce el estado actual de la máquina en vez de retirar todo en silencio». Un servidor atado —concedido contra una clave que administra la persona, `cbm=codebase-memory-mcp`— está concedido pero no instalado, así que aparecía **sin tildar**, y la pantalla no tenía cómo expresar la atadura: alternar una fila producía el nombre pelado, que significa «que Pegasus lo obtenga y lo administre». Medido en una instalación real con `engram` y `cbm` atados: continuar sin tocar nada retiraba los dos artefactos de convención **y reescribía 30 cuerpos de agente** para sacarles las instrucciones de esos servidores —33 actualizaciones contra las 3 del mismo install nombrando las ataduras—, y lo único que salvaba a alguien era leer el preview | Se tomó la primera de las dos salidas que la fila planteaba, la honesta: un servidor atado **es** parte de la instalación, así que abre tildado, con su atadura a la vista, y destildarlo es una remoción deliberada. La atadura viaja en la fila misma —`McpOption.bound_to`, al lado del nombre en vez de sólo un booleano—, y `navigator.mcp_selection` es el único lugar donde la lista de tildes se vuelve selección: re-emite `id=clave` para una fila atada y el nombre pelado para una que Pegasus administra, así que Continue ya no puede pedir que Pegasus obtenga un servidor que la persona ya corre. El estado inicial dejó de derivarse por cuenta propia: `session._recorded_mcp` parsea de vuelta `cli.recorded_mcp_selection` —la misma reconstrucción que `update` reaplica— en lugar de contar entradas `mcp:<id>` del journal, que es justo el conjunto del que una atadura está ausente, así que las dos superficies ya no pueden tener dos opiniones sobre qué hay instalado. El guardián no mira la tilde, que es un proxy, sino el **plan**: instala un servidor atado y uno administrado, recorre la TUI hasta Continue sin tocar ninguna fila, y exige que el plan no retire nada, no reescriba ningún cuerpo de agente, y sea **idéntico** al del `install --dry-run` equivalente por flags; mutar `chosen` de vuelta al conjunto instalado lo hace fallar con los retiros de nuevo, y re-emitir todo pelado lo hace fallar con `mcp:cbm` creado y siete cuerpos reescritos, que es el daño inverso. Una instalación con una atadura cuya clave nunca se registró no se puede reconstruir en absoluto, así que ahí la pantalla muestra el bloqueo —la misma redacción con la que `update`, `mcp grant` y `mcp revoke` ya se niegan— en vez de dibujar filas que Continue reproduciría mal. **No se tocó el CLI**: ya lo hacía bien, y el que mentía era la TUI; lo único que cambió de aquel lado es que `recorded_mcp_selection` y `unresolved_bindings_message` pasaron a ser públicas para que `session` las reuse, sin una segunda reconstrucción ni una segunda redacción del mismo hecho. Y convertir un servidor atado en uno que administra Pegasus, o al revés, **sigue sin estar acá**: una fila dice si el servidor es parte de la instalación y nada más — esa conversión es de `GrantMcpScreen`, y el docstring ahora lo dice |
| `may_delegate_to` no se validaba contra los agentes que el producto embarca, así que un nombre mal escrito renderizaba un permiso muerto en silencio. Lo declaran ocho agentes; el cargador lo pasaba por `_names` y nadie lo miraba después. `render.py` escribe `granted["task"] = {"*": "deny", **{name: "allow" ...}}`, así que un `pegasus-explorar` en vez de `pegasus-explorer` producía una clave `allow` que el runtime nunca consulta: el descriptor cargaba, el agente instalaba, el resto de la lista funcionaba, y el agente podía delegar en un destino menos de los que su autor escribió. Lo cubría un solo test, y sólo para el orquestador | `_require_delegates_to_known_agents` (`src/pegasus/core/content.py`) corre en cada `load()`, igual que `_require_reaches_known_agents` corre para el campo hermano `reaches`, y con el mismo docstring que argumenta por qué: un nombre mal escrito cuesta un destinatario, en silencio, sin que ningún archivo del árbol quede distinto por eso. El chequeo se quedó en el mínimo que cierra el typo: exige que el nombre exista entre los agentes embarcados, nada más. No exige que el destino sea `subagent` -- nada en el contenido o el código afirma esa restricción, y `catalog._delegation_targets` ya trata a un agente nombrándose a sí mismo como una delegación real que el brief de otro puede apuntar, así que la autorreferencia se acepta explícitamente en vez de rechazarse. Tampoco rechaza ciclos: no hay una sola declaración en el contenido que los prohíba, y agregar esa regla sin que algo la pida sería inventar política. Corrida contra el contenido embarcado hoy, la validación no encontró ningún `may_delegate_to` roto de verdad -- los ocho agentes que lo declaran nombran destinos reales -- así que lo que cierra es la ventana futura, no un defecto ya presente. Mutación probada: renombrar un destino real a un typo en un descriptor de prueba lo hace fallar nombrando el archivo y el nombre desconocido; restaurado, vuelve a cargar |
| engram se tomaba del fork propio `balerdis/engram` con los binarios de la 1.20.0 original, cuyo aviso decía «Update available: 1.20.0 -> 3.0.0» y sugería `brew upgrade` | 7.6.2 baja engram 1.20.1, el primer build propio del fork: el aviso mira las releases del fork y dice `pegasus update`. Las decisiones del fork, sus reglas para la base compartida y sus ideas viven en `docs/arquitectura-engram.md` del fork, no acá |

| `pegasus directory grant` sobre una ruta que cae bajo el piso de denegación fijo (`.ssh`, `.aws`, `.credentials`, `.config/gh`, `secrets`) validaba, se registraba en el journal y reportaba éxito sin decir nada más — pero nunca podía tener efecto: el piso se escribe al final de cada map `external_directory` renderizado, así que la resolución `findLast` del runtime siempre lo alcanza a él, sin importar qué otorgamiento se haya escrito antes para esa misma ruta. Distinto del caso ya documentado de un otorgamiento **dormido**: ese recupera sentido el día que la línea de base vuelva a `"ask"`; uno que el piso alcanza no recupera nada nunca, porque el piso gana pase lo que pase con la línea de base | Refusar el comando habría cambiado su contrato para un caso que nadie pidió bloquear, así que se optó por avisar, no rechazar: `render.deny_floor_shadows` (`src/pegasus/adapters/opencode/render.py`) porta fielmente la semántica de comodín del runtime — `packages/core/src/util/wildcard.ts`, escapando metacaracteres de regex, `*` → `.*`, `?` → `.`, anclado en ambos extremos — en vez de aproximarla con un chequeo de componente de ruta, que marcaría un directorio meramente llamado `sshfoo` o dejaría pasar una forma que este chequeo nunca previó. El hecho es específico de OpenCode, así que vive en su adapter y no en `core/content.py` (`core` no puede importar de `adapters`); `cli.directory_grant` es quien la llama, sólo cuando el adapter es `opencode`, y arma un aviso que el reporte JSON expone bajo `warning` y que la prosa en texto plano también imprime. El otorgamiento sigue teniendo éxito y sigue quedando en el journal exactamente igual que antes — lo único que cambia es que ahora se dice la verdad sobre si va a servir de algo | Ninguna: el otorgamiento sobre una ruta que el piso alcanza siempre fue un no-op permanente; lo único que cambió es que ahora el comando lo dice en vez de reportar éxito sin matices |
| El reporte de `mcp grant`/`mcp revoke` ya era honesto para Claude Code, pero el gap que describía seguía sin cerrarse en código: `core/catalog.py` armaba el `mcp=` de `render_agent` sólo con `item.optional_mcp`, nunca con `item.granted_mcp`, así que un grant a una clave atada no escribía ninguna entrada `mcpServers:` en ningún archivo de agente bajo Claude Code — sólo cambiaban el journal y `delegation-capabilities.md`. Medido el 27 de septiembre de 2026 con un usuario descartable: un sub-agente sin la entrada en su `mcpServers:` no veía las herramientas de un servidor que la persona configuró con `claude mcp add`, ni antes ni después del grant | 7.3.3 hiló `item.granted_mcp` dentro de `core.catalog._mcp_for_agent`, como un descriptor atado (`Mcp.bound_to`) sintetizado sin fetch ni definición propia, con exactamente la misma forma que `optional_mcp` ya recibía — ver `tests/test_catalog.py::RenderAgentGrantedMcpTest`. `ClaudeCodeAdapter.mcp_grant_behavior().writes_per_agent_entry` pasó a `True`, y el reporte de `mcp grant`/`mcp revoke` dice ahora lo mismo para las dos CLIs («granted ... to every agent»), derivado del adapter y nunca de una comparación de id — `tests/test_cli_mcp_all_clis.py`. El render de OpenCode, que ya leía `granted_mcp` directamente del `Agent` e ignoraba por completo el parámetro `mcp`, queda byte-idéntico: probado comparando una instalación completa contra la función que este cambio reemplazó (`OpenCodeRenderIsByteIdenticalAcrossTheCatalogChangeTest`) |
| En Claude Code, el orquestador de Pegasus no podía llamar ninguna herramienta MCP, tampoco las de engram, y era el único agente al que le pasaba: medido el 27 de septiembre de 2026 con un usuario descartable y Pegasus 7.3.2, en modo `-p` y confirmado después en una sesión interactiva. La sesión que corre con la identidad `pegasus-orchestrator` arrancaba con seis herramientas nativas, ninguna MCP y sin `ToolSearch`, aunque sus servidores figuraran conectados en `mcpServers:`. Un sub-agente no tenía el problema, aunque su `tools:` sólo nombrara herramientas nativas. Además, al no ver las herramientas el orquestador diagnosticaba mal y se negó a delegar citando la regla de `AGENTS.md` sobre denegaciones del runtime — una lectura incorrecta, porque una herramienta que al agente le falta no es una denegación | 7.3.3 cierra las dos mitades. En el render: el agente de identidad de sesión (`item.default`, `Agent.SESSION_STARTS_IN`) recibe ahora un `mcp__<clave>` por cada servidor de su propio `mcpServers:` — la forma por servidor que exponía las 18 de 18 herramientas de engram en la medición, nunca el comodín `mcp__*`, que es un no-op silencioso — más `ToolSearch`, que resultó necesario porque en una sesión interactiva Claude Code difiere las herramientas MCP y las carga a pedido; un sub-agente queda sin cambios, porque ya alcanzaba sus servidores sin esto (`tests/test_claudecode_adapter.py::SessionIdentityMcpToolsTest`). En el contenido: `AGENTS.md` gana una viñeta nueva, inmediatamente después de «Tell the two denials apart», que distingue una herramienta ausente del propio toolset de una denegación real, dice que delegar en un agente cuyo alcance sí la incluye es legítimo, apunta a `delegation-capabilities.md` como la referencia real de alcance — nunca el `tools:` de un target, que no es el mismo hecho — y dice que instalar o registrar un servidor por cuenta propia no es una decisión del agente. La regla de denegación real queda intacta, palabra por palabra (`tests/test_tool_absence_is_not_a_denial.py`, `tests/test_editing_reach_scope.py`). **Confirmado en interactivo** el mismo día, con todos los servidores arriba. Las 61 herramientas MCP quedan diferidas («loaded on-demand»), y el orquestador las carga con `ToolSearch`: llamó a engram y a cbm, y delegó en `sdd-propose` sin negarse |
| Pegasus no traía una regla de archivos sensibles: su prompt de sistema no le decía a ningún agente que no tocara `.env`, `.ssh/`, `*.pem` y similares, y en la instalación viva esa regla llegaba de rebote por el `~/.claude/CLAUDE.md` que OpenCode cargaba | La sección `## Sensitive Files` de `src/pegasus/content/system-prompt/AGENTS.md` (b93734c), contenido CLI-neutral, así que llega a las dos CLIs. Lleva tres párrafos fijados en `tests/test_sensitive_files_rule.py` (la regla con los nueve nombres textuales, la salida «permiso explícito, para ese archivo» y el alcance), y las raíces en `tests/fixtures/closed-world-vocabulary.json`. Convive con el transporte de credenciales (una credencial pegada en la conversación se usa) y con editar por SSH o `sudo`. La revisión corrigió dos frases del cierre: «no extiende a estos archivos», y que cada agente ya recibe la regla con este prompt, así que va en un brief sólo para un agente que no lo cargue. La otra mitad, el piso de permisos para `.env`, `*.pem` y similares, **se resolvió después** (sección «7.6.0»); DARQ no se tocó |
| OpenCode carga instrucciones y skills de Claude Code sin que Pegasus lo sepa ni lo diga | Se resolvió con un aviso, no cambiando el comportamiento de OpenCode, que sigue cargándolos. `CliAdapter.foreign_loads()` (b591bdf) declara los hechos y `core/foreign_loads.py` los evalúa y redacta igual para `doctor` y para el reporte de `install`/`update`. Declara cuatro variables: `OPENCODE_DISABLE_CLAUDE_CODE`, `..._PROMPT`, `..._SKILLS` y, tras la revisión, `OPENCODE_DISABLE_EXTERNAL_SKILLS`, que también saltea el recorrido de `~/.claude/skills`. Las variables se leen como OpenCode lee un booleano, según su código fuente: `true`/`yes`/`on`/`1`/`y` apagan, `false`/`no`/`off`/`0`/`n` no, con mayúsculas distinguidas, y un valor que OpenCode no acepta se informa en vez de adivinarse. Sólo mira existencia y conteos, nunca abre un archivo. El conteo de skills sigue un symlink de directorio sólo si cuelga directo de la raíz, porque el puerto de filesystem no resuelve rutas reales: puede contar de menos respecto del glob de OpenCode. Está verificado contra el código de OpenCode v1.18.32, no corrido en un OpenCode vivo. DARQ no se tocó |
| Tres residuos del corpus de vocabulario de los chequeos de mundo cerrado (`tests/test_closed_world_vocabulary.py`) | b93734c: la derivación ve ahora un filtro escrito como `for` con `if`; `CRAFT_RULE_SUBJECT` dejó la raíz `config` por `config.yaml`; y `READINESS_STEM` suma «call it good», «good to merge» y «cleared for merge». La revisión encontró que acotar a `config.yaml` perdió formas reales del flag del proyecto, y se amplió a `openspec config` y `project config` (con «'s»), sin volver a la palabra `config` sola; «Honor the openspec config» y «whatever the project config says about testing» entraron al corpus |
| `test_install_script:InterruptedDownloadLeavesNoTempDirTest` y el mecanismo de bash detrás: la máscara de `SIGINT` bloqueada mientras bash espera al hijo de una sustitución de comandos | b107579 cambió `install.sh`: `descargar` ya no corre curl dentro de `$(...)` (el código HTTP va a un archivo junto al destino y se lee con `read`), y los directorios temporales se nombran antes de crearse, con el `trap` armado antes del `mkdir`. El arreglo descansa en el comportamiento documentado de bash, **no en una prueba que lo demuestre**: `test_interrupting_once_curl_is_running_leaves_nothing` pasó 100 de 100 corridas contra el instalador anterior (`f33fbcc`), porque la ventana vieja se cierra antes de que un stub pueda observarla, y un stub que lee su propio `SigBlk` lo encontró vacío en ambos scripts. Esa prueba es un test de humo de conducta: una interrupción con la descarga en vuelo termina el script y no deja nada en el directorio temporal |
| El piso de permisos para archivos sensibles: la regla `## Sensitive Files` sólo estaba en el prompt, nada la hacía cumplir por debajo | Piso en `permissions.ask` de Claude Code y en `read`/`edit` de OpenCode (`ask` para un primario, `deny` para un sub-agente), más una guardia de push ampliada. Qué cubre y qué no, en la sección «7.6.0». Lo que queda sin cubrir está en la misma sección, no escondido. La ruta del shell (`cat .env`) no se cubre con una regla: se atiende con una frase de guía en `## Sensitive Files` para que el agente use la herramienta de archivos (sección «Después de 7.6.0»); es guía al modelo, no cumplimiento |
| `toolCounts` en el plugin de engram se escribía y nunca se leía; 7.2.0 lo dejó a propósito porque sacarlo tocaba tres sitios que esa unidad no necesitaba | Se sacó en 7.7.0 (`b55c14a`), sin cambio de comportamiento |
| `update` dejaba en `<data_dir>/mcp/<nombre>/<versión>` las versiones viejas de los servidores MCP descargados, que ninguna instalación volvía a usar | Desde 7.7.0, después de un install o update exitoso y en `uninstall`, se borran las que no usa ninguna instalación del journal, las fijadas hoy ni la que usaba la CLI antes del update (para que un `restore` siga andando). Mejor esfuerzo, sin seguir symlinks, informado como `pruned_dependencies`. Costo: restaurar más de un update atrás pide `pegasus update` después |
| La captura pasiva de engram no existía bajo Claude Code: el hook del plugin del fork lee un campo `.stdout` que `SubagentStop` nunca manda | Resuelta en 7.7.0 con el hook `SubagentStop` propio de Pegasus, que lee `last_assistant_message` y lo manda a la captura pasiva (sólo guarda con `## Key Learnings`). El transporte de credenciales bajo Claude Code sigue imposible: ver «7.7.0» |

### Deudas disueltas

Una deuda listada más arriba en algún momento del corte puede dejar de tener sujeto porque el diseño que la sostenía cambió, no porque alguien la haya resuelto. Se anota acá, separada de lo entregado, para no confundir "se arregló" con "dejó de aplicar".

| Deuda | Qué la disolvió |
|-------|------------------|
| `pegasus setup` sólo podía reconstruir el venv de una instalación si esa instalación alguna vez corrió desde un checkout, porque esa corrida es la que deja los insumos en `setup-sources/` | Pegasus quedó sin dependencias y el punto de entrada pasó a ser un `zipapp` con shebang y bit ejecutable. Sin dependencias, un venv privado no aísla nada; sin necesidad de aislar nada, no hace falta shim que lo arranque. `pegasus setup`, el venv, el shim y `setup-sources/` se retiraron enteros, y la deuda dejó de tener sobre qué pararse |

---

## Limitaciones aceptadas

Acá no hay nada pendiente, y esa es la razón de separarla de la tabla de arriba. Una deuda declara qué la destraba porque se espera que alguna vez se destrabe; una limitación describe cómo funciona el producto a propósito, con el motivo por el que se eligió así. Mezclarlas en una sola tabla promete en silencio un arreglo para lo que no va a arreglarse. Una fila se muda de acá para arriba sólo si la decisión se reabre.

| Limitación | Por qué es así | Qué hacer al respecto |
|------------|----------------|-----------------------|
| La TUI no expone `directory grant` ni `revoke`, mientras sí expone `mcp grant`. La invariante del proyecto va en una sola dirección —toda acción de la TUI tiene comando equivalente— así que nada falla, pero es una asimetría con el precedente que este mismo cambio dice estar copiando | Conceder un directorio es una acción rara y deliberada, del tipo que uno tipea una vez; atar un servidor MCP se hace durante una instalación guiada, que es donde la TUI gana de verdad. La invariante va en una sola dirección —toda acción de la TUI tiene comando equivalente, no al revés—, así que la asimetría no rompe nada, y la paridad inversa no se buscó porque no compra nada. Esta fila es ese porqué puesto por escrito, que es lo único que faltaba | Conceder un directorio se tipea una vez con `pegasus directory grant` y se saca con `pegasus directory revoke`; la TUI no hace falta para eso |
| El plugin de Zellij usa `pegasus-zellij-state` como nombre de directorio en `~/.config/` y `~/.cache/`, y ahí la marca del motor se queda. El archivo del plugin sí se deriva, así que una distribución termina con un `darq-zellij-state.ts` escribiendo en un `~/.config/pegasus-zellij-state/`: una asimetría deliberada, no un olvido | Derivar esos dos nombres es de una línea: el problema no es el código sino el estado que ya está adentro. Esos directorios viven fuera del directorio de configuración del CLI, el journal no los reclama y ningún retiro los alcanza, así que derivarlos huerfanizaría en silencio lo que la persona ya tiene y la instalación arrancaría con estado limpio sin decírselo. Se decidió sostener la asimetría hasta que haya una migración explícita que mueva el directorio, y el motivo quedó escrito adentro del propio `.ts` para que nadie lo «arregle» sin verlo | Nada: el directorio se llama así aunque la distribución tenga otro nombre, y renombrarlo a mano deja al plugin sin encontrar su propio estado |
| Una edición a mano sobre un artefacto que Pegasus instaló no sobrevive: el próximo `install` o `update` la reescribe con la versión del release, y `uninstall` la borra, sin preguntar en ninguno de los dos casos. Vale igual para una clave de configuración que Pegasus posee dentro de `opencode.json` | La huella dejó de ser permiso en la unidad 9: pertenecer al journal alcanza para actualizar y para retirar (`_file_step` y `retire`, `src/pegasus/core/planner.py`). Lo que protege una edición es el snapshot previo a escribir, no una negativa a escribir — separar «recuperar» de «pisar» es lo que evita que una edición ajena congele para siempre una dirección que el producto necesita poder mover | Desde 5.35.0 no hace falta saberlo de antes: el propio aviso de `install` y `update` nombra `pegasus restore` y cuántas generaciones se retienen, derivado de la constante. Recuperarla con `pegasus restore [generación]`, que devuelve los bytes y el modo exactos previos al comando, con **20 generaciones** de retención y no más (`RETAIN_GENERATIONS`, `src/pegasus/cli.py`). Antes de aplicar, `--dry-run` adelanta qué se va a pisar. Para que un cambio propio dure: no se hace sobre un archivo de Pegasus — se construye una distribución propia, o se guarda una copia fuera del directorio de configuración del CLI |
| Un item agregado a una lista —un `append`— queda afuera del aviso `overwritten`, así que una edición tuya sobre uno de esos se pisa sin que nada lo cuente | Se lo localiza por huella, no por dirección: si el valor difiere, no se encuentra, y «alguien editó el nuestro» es indistinguible de «alguien borró el nuestro y agregó el suyo». Avisar sobre lo segundo sería inventar un conflicto donde no lo hay | Nada lo detecta de antemano. El snapshot lo cubre igual: `pegasus restore` devuelve el archivo entero como estaba antes del comando |
| `uninstall` no tiene aviso equivalente al `overwritten` de `install` y `update`: borra cada dirección reclamada e informa el id que sacó, sin decir si el contenido que había ahí era el del release o uno tuyo | `install` tiene que leer cada dirección para decidir si hace falta escribirla, así que la comparación contra la huella le sale gratis. `uninstall` no necesita leer nada para borrar, y leerlo todo sólo para poder avisar sería trabajo agregado para una advertencia que llega cuando ya decidiste desinstalar | `pegasus restore` inmediatamente después, que devuelve el estado exacto anterior al `uninstall` — verificado ejecutándolo, con la edición a mano incluida. Desde 5.35.0 el propio reporte del `uninstall` lo nombra, con su límite de generaciones, en vez de dejar la promesa sólo en el manual. Si hay algo propio conviviendo con artefactos de Pegasus, copiarlo afuera antes |
| `render._permission` renderiza `external_directory` con línea de base `"*": "allow"` para todo agente y toda profundidad, sin preguntar por ningún acceso fuera del árbol del proyecto. La expone —no la motiva— un bug abierto de OpenCode: en `packages/tui/src/routes/session/index.tsx`, la vista que lista permisos pendientes sólo mira un nivel de sesión (`children()` filtra por `parentID === session().id`, y `permissions()` devuelve `[]` apenas `session()?.parentID` existe), así que el `ask` de un sub-agente a profundidad ≥ 2 nunca aparece en ninguna pantalla y la llamada de herramienta se cuelga para siempre, sin límite de tiempo — issues `anomalyco/opencode#39112` (abierto), `#43996` (abierto), `#44747` (abierto), y `#30635` (cerrado arreglando sólo un nivel). Pegasus embarca `subagent_depth: 10` desde 5.39.0, así que esa profundidad es habitual, no una rareza: se reprodujo en vivo con `pegasus-orchestrator` → `pegasus-general` → `pegasus-explorer`. El costo es real y se acepta a sabiendas: la línea de base deja de preguntar también en profundidad 0 y 1, donde sí preguntaba bien, y `pegasus directory grant` queda dormido para una ruta ordinaria, no inútil — su propia entrada sigue en el journal y se sigue renderizando igual, y recuperaría su sentido completo sin que haga falta volver a otorgarla si la línea de base volviera a `"ask"`. Lo único que sigue denegado en su grafía canónica es un piso fijo y chico (`.ssh/`, `.aws/`, `.credentials/`, `.config/gh/`, `secrets/`), escrito después de cualquier concesión para que gane bajo la resolución `findLast` del runtime — necesariamente por directorio, nunca por archivo, porque el runtime sólo pregunta por `dirname(destino) + "/*"`, nunca por el archivo mismo. Ese piso hay que leerlo por lo que es y no por lo que suena: el match es sobre el string literal, sin `realpath` en ningún lado, así que es un guardia contra quien entra por accidente, no una frontera contra quien entra a propósito — un symlink, un bind mount, o una variable como `GH_CONFIG_DIR`/`AWS_SHARED_CREDENTIALS_FILE` lo atraviesan sin tocarlo, y un agente con `bash` bajo esta misma línea de base `allow` puede construir esa vuelta él mismo. Y todo lo que el piso no alcanza por construcción — un `*.pem`, un `*.key`, un `.env` que viva fuera de esos cinco directorios, que es casi cualquier otro lugar — queda alcanzable de verdad, no sólo "sin guardia en abstracto" | Habilitar `external_directory` por default es una decisión de producto, tomada con el costo de la columna anterior a la vista: en el uso cotidiano, tener eso habilitado es una ventaja. El bug abierto de OpenCode (`#39112` y las hermanas `#43996`/`#44747`) no la motiva, sólo la expuso: hizo visible en vivo cuánto costaba la alternativa —un `ask` a profundidad que se cuelga para siempre en vez de preguntar o fallar— frente a esa ventaja de uso cotidiano. Si esos issues se resuelven río arriba, eso no revierte por sí solo esta línea de base en `_permission` (`src/pegasus/adapters/opencode/render.py`): la decisión tendría que reabrirse pesando de nuevo la ventaja contra el costo, no darse vuelta sola porque el bug que la expuso ya no está. El piso de denegación (`EXTERNAL_DIRECTORY_DENY_FLOOR`) es una decisión aparte: nada en ésta, ni un arreglo upstream, obliga a sacarlo | Un directorio otorgado con `pegasus directory grant` no cambia nada observable salvo que solapara uno de los cinco directorios siempre denegados, en cuyo caso sigue denegado igual — pero no lo revoques por eso: sigue guardado por si la línea de base volviera a `"ask"`. Nadie debe asumir que un permiso de `external_directory` sirve de gate contra un agente decidido — no lo es, para ningún agente, a ninguna profundidad, ni siquiera dentro de los cinco directorios del piso |
| `ProcedureIsLazyTest` es léxico: impide que un cuerpo que se carga siempre nombre `ftd-procedure.md` o su frase distintiva, pero no ve un cuerpo que parafrasee su contenido con otras palabras. Hoy ninguno lo hace | Un chequeo de texto no reconoce una paráfrasis, y no hay arreglo barato que lo haga: reconocerla es juzgar el significado, que es trabajo de una revisión y no de un test. Un corpus de sinónimos tampoco alcanza, porque parafrasear un procedimiento no es cambiar una palabra por otra. Lo mecánico sí está cubierto —el nombre del archivo, su frase distintiva y el único puntero, a la salida de la ruta FTD—. Se acarreó como deuda hasta que quedó claro que nada la destraba | Al revisar un cambio a un cuerpo que se carga siempre —cada agente, sus secciones MCP y el prompt de sistema—, mirar a mano que no repita el procedimiento FTD con otras palabras |

## Verificación de la arquitectura

Tests que fallan si el diseño se degrada:

- [ ] Ningún módulo fuera de `adapters/` menciona el id de un CLI
- [ ] El registry rechaza un adapter con manifiesto incoherente
- [ ] El catálogo commiteado coincide con el generado desde el contenido
- [ ] Cada acción de la TUI tiene comando equivalente
- [ ] Cada capacidad declarada en `True` tiene ruta y render
- [ ] Cada códec serializa de forma canónica y preserva las claves que Pegasus no escribió
- [ ] El journal rechaza targets fuera del home del usuario
- [ ] Instalar y desinstalar escriben lo que el journal reclama sin consultar la huella del artefacto
- [ ] Toda instalación y toda desinstalación toma un snapshot antes de escribir
- [ ] `restore` devuelve bytes y modo exactos, sin merge ni reconstrucción
- [ ] Desinstalar deja el sistema sin rastros de Pegasus, incluido lo que el usuario modificó sobre una dirección propia; lo único que puede quedar es un ítem de lista que no se pudo identificar
- [ ] La retención acota la historia de snapshots, y una limpieza que falla no vuelve fallido el comando que ya escribió
- [ ] Instalar retira lo que el journal reclama y el render ya no produce, y el snapshot cubre esas direcciones
- [ ] El journal descarta lo que el retiro confirmó haber removido, nunca lo que se pretendía remover

---

## Próximo paso

El corte numerado quedó completo y **4.0.0 se publicó**: tag, wheel, evidencia y una instalación hecha de punta a punta en una cuenta Linux limpia, bajando el release desde donde lo baja cualquiera.

**4.1.0 cerró lo que 4.0.0 dejó anotado.** Los cuatro servidores MCP se instalan: a `context7` y `engram` se suman `cbm` y `playwright`.

Dos de los bloqueos que 4.0.0 escribió no existían del todo, y averiguarlo fue el trabajo. CBM decía no tener URL publicada — cierto de este repo, no del mundo: el proyecto publica releases con binario y su propio archivo de checksums, así que el hash lo pone él y no nosotros. Y el lockfile de un solo paquete se resolvió haciendo que el completo viaje al lado del descriptor; en el camino apareció que el `package.json` sintetizado se nombraba a sí mismo distinto de lo que el lockfile declara, que es justo uno de los campos que `npm ci` mira para decidir si están sincronizados: toda instalación de playwright habría fallado.

También se cerraron el esfuerzo de razonamiento, que se guardaba sin llegar nunca a la configuración —el schema del CLI lo acepta como `variant`, y esa era la evidencia que faltaba— y el último agujero de paridad: la TUI ya deja elegir qué servidores instalar. Ahí apareció el defecto más caro de los tres, porque estaba entregado y en silencio: la pantalla nunca pasaba ese parámetro, así que cada instalación desde la TUI instalaba cero servidores y al reinstalar retiraba lo que una corrida con flags hubiera puesto.

Y salió del árbol lo que quedaba de la distribución de v3: el binario vendorizado de 37 MB que el propio diseño prohíbe, y los manifiestos que lo describían.

**Después de 4.1.0, Pegasus se quedó sin dependencias de terceros.** Con eso resuelto, el venv privado dejó de aislar nada, así que el punto de entrada cambió de shim más venv a un único `zipapp` con shebang y bit ejecutable (`tools/build_zipapp.py`), acompañado de su `.sha256`. Instalar pasa a ser bajar dos archivos, verificar el checksum y dejar el ejecutable en el PATH — sin wheel, sin `pip install`, sin `pegasus setup`. Esto sólo era viable porque, en paralelo, el contenido y los assets de los adapters aprendieron a leerse también desde adentro de un zip.

**De 5.1.0 a 5.8.0 el producto dejó de crecer por plan y empezó a crecer por evidencia.** Nueve releases, y casi ninguna nació de una unidad: nacieron de mirar una instalación viva y encontrar que el producto prometía algo que no cumplía. La línea de base `{"*": "deny"}` negaba el `skill` que pone el inventario delante de un agente, y también el `external_directory` sin el cual ningún agente podía leer las skills que Pegasus le instala; el contrato común de engram no llegaba a nadie porque ningún agente declaraba el servidor; los párrafos de un MCP quedaban en el prompt aunque el servidor no se hubiera elegido; el comodín de un grant alcanzaba lo que destruye estado; `doctor` afirmaba que no había servidores configurados en una máquina que tenía seis. Todo eso está en "Lo que se agregó después del corte" y en las deudas resueltas.

La lección que deja esa serie es de método y no de diseño: **cada uno de esos defectos era invisible desde el repositorio y evidente desde una instalación**. La suite verificaba que el archivo se escribiera; lo que faltaba era preguntarle al runtime qué había entendido. `opencode debug agent`, un handshake real, un `chmod` sobre un árbol de dos archivos — las herramientas que encontraron los defectos fueron siempre las que ejercitan, no las que inspeccionan.

**Lo que sigue.** La migración de tests que la unidad 10 dejó a medio camino se cerró, y de paso corrigió cómo estaba descripta: `test_journal_store.py` y `test_snapshot_store.py` nunca migraron nada — conservaron sus casos contra el doble y **agregaron** una clase corta contra disco real, porque el doble prueba la política y el disco prueba que las dos mitades componen. `test_model_assignment_store.py` y `tests/test_dependencies.py` recibieron esa misma contraparte: modos reales, round-trip real, y la limpieza de un árbol escrito a medias, que es lo que un doble respaldado por un diccionario no puede desmentir. Lo que no se movió tampoco debía moverse: los casos que inyectan una falla —«permission denied», «no space left on device»— no se producen contra un disco real de forma determinística, y los dobles de `test_dependencies.py` son una red y un `npm ci`, que no son de lo que esta deuda hablaba. El resto vive en «Deudas sin unidad asignada», acarreado a propósito.

**v7 está en implementación.** Sus decisiones —FTD como carril habitual del trabajo ordinario, la escalera de cuatro rutas con sus routing facts, el record en `docs/ftd/` y Strict TDD fuera de SDD— viven en [v7: FTD y la escalera de rutas](#v7-ftd-y-la-escalera-de-rutas). El plan de slices quedó aprobado ahí, y el progreso de cada slice se anota en esa sección, no acá.

## 7.1.0: a quién le toca escribir en Engram

El diagnóstico que motivó este release era observable en cualquier sesión de OpenCode: todo sub-agente de Pegasus (`pegasus-verifier`, `pegasus-implementer`, `pegasus-general`, cada fase SDD) terminaba su turno con `mem_save`/`mem_update` y `mem_session_summary` incluso cuando había estado bloqueado y no había hecho nada, y `pegasus-orchestrator` —a menudo un modelo literal corriendo a esfuerzo bajo— repetía `mem_update` + `mem_session_summary` después de cada delegación. La causa era una sola redacción repetida en cuatro lugares que todo agente carga sin excepción de sub-agente: el bloque ambient (`system-prompt/mcp/engram.md`), la convención (`mcp/engram.md`), el fragmento por agente (`agents/mcp/engram.md`) y el plugin de OpenCode (`assets/plugins/engram.ts`), cuyo `MEMORY_INSTRUCTIONS` se inyecta en el prompt de sistema de **toda** sesión — root y sub-agente por igual — pese a que el propio plugin ya rastrea `subAgentSessions` y las excluye de `chat.message` y de `tool.execute.after`. El único freno existente, «los sub-agentes no llaman a `mem_session_summary`», alcanzaba sólo a las fases SDD.

La decisión del usuario, textual: «los subagentes dejan de escribir en engram del todo y solo escriben cuando el brief se los pide». Se implementó como una condición de situación, no una lista de agentes: un agente lanzado por otro agente no hace ninguna escritura de memoria (`mem_save`, `mem_update`, `mem_session_summary`, ni el `mem_judge` que sigue a un save) salvo que su brief se lo pida; puede seguir leyendo (`mem_search`, `mem_context`, `mem_get_observation`). Quien lo lanzó decide qué guardar a partir de lo que ese agente devuelve. El agente que habla con la persona conserva los disparadores de guardado proactivo, pero se le retiró la presión que convertía cada fin de tarea en un guardado obligado («save NOW», «esperar a que te lo pidan es el modo de fallo») a favor de una regla explícita: si no pasó nada durable, no hay nada que guardar. `mem_session_summary` quedó reservado a ese mismo agente y sólo en un cierre real —la persona dice que termina, o lo pide, más la recuperación tras compactación ya existente—; terminar una tarea, recibir una delegación o entregar una respuesta no es un cierre, y decir «listo» tampoco.

Para las fases SDD no hizo falta una regla nueva: el `Artifact store mode` que el orquestador ya inyecta en cada lanzamiento (`_shared/persistence-contract.md`, sección «Orchestrator Prompt Instructions for Sub-Agents») **es** el brief pidiendo esa escritura puntual, y ninguna fase estaba autorizada a guardar otra cosa (`mem_session_summary` ya estaba prohibido para sub-agentes en dos lugares). Se dejó explícito en `persistence-contract.md` y `sdd-phase-common.md` para que la regla general y la excepción SDD queden escritas una al lado de la otra, en vez de que la segunda parezca una laguna de la primera.

El plugin fue el punto donde la decisión no pudo aplicarse de la forma más simple. La opción preferida —borrar la inyección de `experimental.chat.system.transform` y dejar el bloque ambient como único protocolo— exigía que ambos se instalaran bajo la misma condición. No es así: `engram.ts` se copia en **toda** instalación de OpenCode (es un asset fijo del adapter, sin condición de selección de MCP), mientras que el bloque ambient y el fragmento por agente sólo se instalan cuando `engram` está entre los MCP elegidos (`core/content.py`, el filtro por `kept`). Hay una instalación real donde el plugin llega solo: quien instala OpenCode sin elegir el MCP `engram` igual recibe el plugin con `MEMORY_INSTRUCTIONS` inyectándose en cada mensaje, sin el bloque que ahora dice cuándo aplica. Por eso se mantuvo la inyección — pero sólo para la sesión raíz: `experimental.chat.system.transform` y `experimental.session.compacting` ahora retornan temprano cuando `input.sessionID` está en `subAgentSessions`, el mismo conjunto que ya usan `chat.message` y `tool.execute.after`, y el texto de `MEMORY_INSTRUCTIONS` se realineó con la misma regla de alcance. El resto del plugin —captura pasiva, ciclo de vida de sesión, supresión de sub-agente— se dejó byte a byte igual, con un comentario en cada punto tocado explicando por qué diverge.

De paso quedó anotada una duda que no se resolvió, a propósito: `tool.execute.after` compara `input.tool === "Task"` con mayúscula exacta, mientras la misma función ya normaliza a minúscula para comparar contra `ENGRAM_TOOLS` (`input.tool.toLowerCase()`), y el plugin vecino `apply-patch-scope.ts` lee su propio tool id como `apply_patch`, en minúscula y con guión bajo. Es evidencia, no prueba, de que OpenCode 1.18 podría exponer el tool de sub-agente como `task` y no `Task` — en cuyo caso la captura pasiva de la salida de `Task` nunca dispara. Se deja como deuda para quien tenga forma de observar el runtime real, no como un arreglo especulativo.

Una revisión independiente del diff encontró y corrigió tres huecos antes del cierre: el template Non-SDD que el orquestador inyecta en cada lanzamiento de sub-agente seguía mandando «you MUST save them to engram before returning» — la vía de delegación más común contradecía la decisión del usuario en el propio texto que el orquestador escribe; la sección «After Compaction» de la convención decía, sin condición, «IMMEDIATELY call `mem_session_summary`» — sin la misma guardia de rol que el bloque ambient sí lleva; y en `engram.ts`, el guard de `experimental.chat.system.transform` (`input.sessionID && subAgentSessions.has(...)`) fallaba abierto cuando `sessionID` faltaba, porque ese campo es opcional en el hook. Los tres quedaron corregidos: el template Non-SDD ahora pide al sub-agente que devuelva hallazgos durables en su respuesta en vez de mandatar un guardado, y sólo lleva una línea de escritura puntual cuando quien lanza la pide explícitamente; «After Compaction» quedó bajo la misma condición «si sos el agente que habla con la persona»; y el guard del plugin ahora falla cerrado (`!input.sessionID || subAgentSessions.has(...)`) — sin `sessionID` no inyecta, razonamiento que queda anotado en el comentario junto al guard.

Quedaba una deuda anotada y no arreglada: `subAgentSessions` se llena desde el evento `session.created`, y el early-return de `chat.system.transform` asume que ese evento llega antes de que se arme el primer system prompt de la sesión hija.

**El 27 de septiembre de 2026 se verificó contra el código de OpenCode v1.18.32, la versión que se usa, y el orden está garantizado.** La garantía sale de cómo están escritos hoy los dos lados, no de un contrato:

- `Session.create` publica `session.created` y espera esa publicación antes de devolver (`packages/opencode/src/session/session.ts:535`).
- El listener que reparte los eventos a los plugins los llama sin esperarlos (`void hook["event"]?.(...)`, `packages/opencode/src/plugin/index.ts:255-262`). Pero una función `async` corre en forma sincrónica hasta su primer `await`, y la rama de sub-agente de `session.created` en `engram.ts` no tiene ninguno antes de `subAgentSessions.add(sessionId)`.
- Por eso la sesión hija ya está en el conjunto cuando `task` lanza su primer prompt y se dispara `experimental.chat.system.transform` (`packages/opencode/src/session/llm/request.ts:69-73`).

La compactación corre mucho después, así que queda cubierta con más razón.

**Lo que puede romperlo, y cómo se vería.** Hay dos causas posibles: que alguien agregue un `await` antes de ese `add()` en `engram.ts`, o que OpenCode cambie cómo les reparte los eventos a los plugins. En los dos casos el síntoma sería el de antes de 7.1.0: los sub-agentes vuelven a recibir las instrucciones de memoria y a guardar en engram, sobre todo en su primer turno.

**Si el plugin de engram deja de funcionar así, sospechar primero de este orden.** El arreglo que no depende del orden ya está identificado. En el transform, si la sesión no está en el conjunto, se le pregunta por ella a OpenCode con `client.session.get({ path: { id } })`, que devuelve su `parentID`, y se la trata como sub-agente si lo tiene. Hoy no hace falta. Además cuesta una llamada por cada turno de una sesión raíz, salvo que también se recuerde cuáles ya se confirmaron como raíz.

## 7.2.0: el disparador de captura pasiva estaba muerto, y le faltaba el contrato de formato

El diagnóstico tenía dos partes independientes, y las dos hacían falta para que la captura pasiva de un sub-agente sirviera de algo. La primera: `tool.execute.after` comparaba `input.tool === "Task"` con mayúscula exacta — la deuda que 7.1.0 dejó anotada como duda, no como hallazgo. Se resolvió acá con evidencia directa: una base de datos real de OpenCode registra ese tool id 5171 veces, las 5171 en minúscula (`task`), 0 en `Task`. El disparador nunca corrió en una instalación real; `Task` es el nombre del tool de sub-agente en el harness ajeno del que este código se adaptó, no el que usa OpenCode. La segunda parte, que ninguna versión anterior había señalado: aun si el disparador hubiera corrido, el texto que mandaba —`typeof output === "string" ? output : JSON.stringify(output)`— era casi siempre el segundo caso, porque `tool.execute.after` entrega `output` como un objeto `{ title, output, metadata }` (confirmado contra `@opencode-ai/plugin/dist/index.d.ts`), no un string. `JSON.stringify` escapa los saltos de línea a `\n` literal, y el extractor de engram sólo reconoce encabezados y listas en inicio de línea real (`(?m)^#{2,3}\s+...`); un `## Key Learnings` dentro de un dump JSON nunca hace match. Faltaba el disparador y faltaba, por separado, el contrato de formato que hiciera algo capturable del otro lado.

**Qué hace engram v1.20.0 con el texto posteado.** Por `internal/store/store.go`, funciones `ExtractLearnings` y `PassiveCapture` (compartidas por el endpoint HTTP `/observations/passive` y la tool MCP `mem_capture_passive`): no guarda nada salvo que el texto tenga un encabezado que matchee `(?im)^#{2,3}\s+(?:Aprendizajes(?:\s+Clave)?|Key\s+Learnings?|Learnings?):?\s*$`; usa la ÚLTIMA sección así que produzca ítems válidos (una sección termina en el próximo heading `#{1,3} `); extrae ítems numerados (`^\s*\d+[.)]\s+(.+)`, primera línea sola) y, si no hay ninguno, cae a bullets (`^\s*[-*]\s+(.+)`); cada ítem necesita 20 o más caracteres y 4 o más palabras tras despojar negrita, itálica e inline-code; cada ítem se guarda como observación separada, tipo `passive`, scope project, asociada al `session_id` posteado — que es la sesión de quien lanzó, porque el hook corre en el padre; el resto del texto se descarta; el dedupe es por hash normalizado dentro del proyecto.

**El origen de `Task`.** Es evidencia de importación cruzada, no una elección de este repo: el commit del harness ajeno que agregó esta captura pasiva (1d2a558, 2026-02-21) la escribió junto al hook `SubagentStop` de ese harness en la misma sesión de trabajo, y ese hook sí expone un tool id capitalizado. El plugin de OpenCode se copió de una instalación en uso (ver 7.1.0 más arriba) que a su vez había adaptado ese código sin corregir el id.

**Alternativas de disparador consideradas.** `session.idle` se descartó porque exige que el propio plugin haga un fetch al cliente para reconstruir qué terminó y con qué salida — trabajo que `tool.execute.after` ya recibe gratis en sus argumentos. `session.created` se descartó porque es el momento equivocado: dispara al *empezar* la sesión del sub-agente, no cuando termina y hay una salida que capturar. `message.part.updated` se descartó por ruido: dispara por cada parte de cada mensaje mientras se arma, muchas veces por turno, y habría exigido su propia lógica para detectar "esto es la respuesta final de un sub-agente" — lógica que `tool.execute.after` ya resuelve al ser, precisamente, el hook de fin de ejecución de una tool. `tool.execute.after` sobre el tool de sub-agente, case-insensitive, fue la opción que no exige inventar detección de "sub-agente terminado": ya la tiene.

**La decisión del usuario — opción 2 — y por qué no las otras.** Se evaluaron tres formas de cerrar el hallazgo. Borrar la captura pasiva entera evitaba el riesgo de reabrir una escritura no pedida, pero tiraba una capacidad real (que un sub-agente deje algo guardado sin llamar ninguna tool de memoria) por un bug de comparación de string. Pedir siempre la sección — inyectarla como mandato incondicional en el `MEMORY_INSTRUCTIONS` o el bloque ambient — reabría exactamente la presión que 7.1.0 retiró: todo sub-agente, incluido uno bloqueado o literal, terminaría escribiendo una sección `## Key Learnings` con ítems inventados para llenar el formato, inundando el proyecto de observaciones sin valor. La opción elegida —arreglar el disparador y que un sub-agente escriba la sección sólo cuando su brief se lo pide— mantiene la regla de 7.1.0 intacta: el brief pidiendo la sección ES la solicitud de guardado, igual que el `Artifact store mode` ya es la solicitud de guardado de una fase SDD; el sub-agente sigue sin llamar ninguna tool de memoria.

**Dónde no hay mecanismo condicional por adapter.** Se buscó, antes de escribir el contenido, si `core/content.py` o algún adapter tienen una forma de renderizar un párrafo distinto según el CLI de destino (placeholders, fragmentos por adapter). No la hay: el único campo que alguna vez prometió algo parecido (`compatibility`) está documentado como aceptado y nunca consumido por ningún renderer. La redacción de "quién revisa que el guardado automático haya llegado" quedó entonces escrita para que valga en los dos casos a la vez —quien lanzó revisa que los ítems del `## Key Learnings` hayan llegado a memoria y, si no, los guarda él mismo— en vez de una rama por adapter que el pipeline de contenido no puede expresar hoy.

**Deudas, no arregladas:**

- Claude Code no tiene un equivalente de esta captura. Su hook de engram lee un campo `.stdout` que el evento `SubagentStop` de Claude Code no manda — manda `last_assistant_message`, según la documentación de Claude Code. Un `## Key Learnings` en la respuesta de un sub-agente de Claude Code no se guarda solo hoy; por eso el contenido ambient y la convención no afirman el guardado automático sin condición — el `MEMORY_INSTRUCTIONS` del plugin (que sólo se instala donde la captura corre) es la señal: si las instrucciones propias de quien lanzó afirman el guardado automático, lo deja así; si no, lo guarda él mismo a partir de la respuesta. Ninguna de las dos redacciones pide buscar en memoria para confirmar si llegó — eso abriría un loop de verificación que un orquestador literal correría después de cada delegación. **Resuelto en 7.7.0:** el hook `SubagentStop` propio de Pegasus lo reemplaza y lee `last_assistant_message`; ver «7.7.0».
- **Resuelto en 7.3.0, por diseño, no por parche.** Un sub-agente lanzado por otro sub-agente nunca veía su sección capturada: `tool.execute.after` posteaba con el `session_id` de la sesión bajo la que corrió la tool `task`/`subagent` — la sesión del sub-agente que lanzó, no la raíz, cuando quien lanza ya es en sí mismo un sub-agente. Esa sesión nunca se registró en engram (`ensureSession` la excluye explícitamente vía `subAgentSessions`, ver 7.1.0 más arriba), así que el servidor —que exige que la sesión exista y matchee el proyecto— rechazaba el POST; y `engramFetch` no chequea `res.ok` ni deja escapar la excepción hacia afuera, así que el rechazo no se veía en ningún lado. La decisión no fue arreglar ese POST para que llegue — fue dejar de mandarlo: un sub-agente nunca lanza sus propios sub-agentes pidiéndoles una sección `## Key Learnings`, porque el criterio de qué vale la pena guardar es del agente que habla con la persona, no de uno intermedio. Lo que un sub-sub-agente encuentra llega a memoria igual, por la propia sección `## Key Learnings` del agente intermedio — esa sí se captura, bajo la sesión raíz, cuando la tool que lanzó al sub-sub-agente termina. `tool.execute.after` ahora chequea `subAgentSessions.has(sessionId)` sobre la sesión que corrió la tool, antes de postear, y si es un sub-agente no postea nada — ver `src/pegasus/adapters/opencode/assets/plugins/engram.ts`.
- La revisión de sensibilidad de qué se postea a `/observations/passive` —la respuesta entera de un sub-agente, no sólo la sección `## Key Learnings`, sale hacia `stripPrivateTags` y de ahí a un servidor local— quedó explícitamente para el siguiente paso, a pedido del usuario. No se tocó en este release.
- El disparador también acepta `subagent`, un nombre que al principio era un reporte sin verificar. **Se verificó el 27 de septiembre de 2026:**
  - En OpenCode v1.18.32 y en la rama `dev` no existe; ahí la tool sigue siendo `task` (`packages/opencode/src/tool/task.ts:24`).
  - Sí existe en la línea 2.x, que hoy va por separado: el tag v2.0.18 registra `subagent` en `packages/core/src/tool/plugin/subagent.ts`. Su schema es distinto: puede continuar una sesión por `sessionID` y tiene un modo `background`.
  - La base real de OpenCode del usuario muestra 5183 llamadas a `task` y ninguna a `subagent`.

  **Se queda a propósito, como preparación para OpenCode 2** («hay que irse preparando para la versión 2 de opencode»). No cuesta nada mientras `task` sea el id real, y cubre el día en que la línea 2.x llegue a la versión que se usa. Ese día hay que verificar además que la salida de la tool nueva siga trayendo la respuesta del sub-agente donde el disparador la lee (`output.output`), porque el schema cambió.

**La duda que 7.1.0 dejó anotada sobre el casing de `Task`** —«se deja como deuda para quien tenga forma de observar el runtime real, no como un arreglo especulativo», en la sección «7.1.0: a quién le toca escribir en Engram» más arriba— queda resuelta acá: dejó de ser una duda sin observación posible y pasó a ser el hallazgo con evidencia (5171/5171 filas en minúscula) que motivó este release y el fix descrito arriba.

## 7.3.0: transporte de credenciales

**El problema, en palabras del usuario.** «cuando le paso credenciales, el tipo se la pasa diciendo que debo rotarlas y yo necesito trabajar, y no me puedo poner a prepararle en variables de entorno o en un archivo las credenciales, me cansa esa situación, termino optando por pasárselas por el chat y listo... (entiendo lo que queda en el chat y luego queda expuesta, pero no tengo una forma rápida y efectiva de trabajar con ese tema)». Antes de este release, el orquestador pegaba la credencial completa en el brief de un sub-agente, un comando la hacía eco, quedaba en el historial de sesión de OpenCode, y el plugin de engram guardaba cada mensaje del usuario de más de diez caracteres como un prompt — la credencial incluida.

**Las cuatro decisiones del usuario, vinculantes:**

1. **Detección automática, sin marcador.** Nunca por "parece aleatorio": un hash o checksum bare (un commit de 40 hex, un sha256 de 64 hex, un UUID, un número) no se marca nunca, porque se pegan todo el tiempo y tienen que sobrevivir. La detección es por CONTEXTO: un valor al lado de un nombre de clave sensible, un header de autenticación, una contraseña en una URL, o un formato de token conocido. `<private>…</private>` (opcionalmente `<private>NOMBRE=valor</private>`) sigue funcionando como fallback explícito para lo que la detección no alcance — engram ya honraba `<private>` desde antes.
2. **Los valores viven sólo en memoria**, durante la vida del proceso de OpenCode, compartidos por todas las sesiones de ese proceso (sub-agentes incluidos). Nada se escribe a disco.
3. **Sin filtro de salida en vivo**: se acepta el hueco de que un comando que imprime el valor en medio de su ejecución lo deja en el historial/la TUI (el modelo nunca lo ve). Se documenta acá, y se mitiga sólo con una regla de contenido: nunca imprimir una variable de credencial — nada de `echo`, nada de flag verboso que vuelque headers.
4. **Split hexagonal**: CORE (agnóstico de CLI) son las reglas de contenido en el system prompt ambiente más el catálogo de detección como DATO, no TypeScript, definido una sola vez. PORT es una capacidad de adapter, "credential transport", con cuatro operaciones —detectar+reemplazar en la entrada, inyectar en la ejecución, redactar en la salida, redactar antes de escribir a memoria— que cada adapter declara por separado. ADAPTER: OpenCode implementa las cuatro ahora; Claude Code, adapter registrado desde 6.0.0, no declara ninguna (no implementa `credential_transport()`, así que el default por duck-typing lo resuelve en las cuatro `False` — deuda, evaluar cada operación cuando se le agregue soporte real), y las reglas de contenido igual se renderizan para cualquier CLI.

**Internals verificados de OpenCode 1.18.32** (fuente: el tag `v1.18.32` del proyecto de OpenCode, código abierto): `chat.message` dispara ANTES de que las partes del mensaje del usuario se persistan (`session/prompt.ts:999-1047`); mutar `output.parts[i].text` in place cambia lo que se guarda, lo que ve el modelo, y el título. También dispara para el brief de cada sub-agente (`task.ts` llama a `prompt` sobre la sesión hija). `shell.env` (entrada `{cwd, sessionID?, callID?}`, salida `{env}`) se mergea al entorno de todo spawn de bash/PTY (`{...process.env, ...extra}`), cualquier sesión; el texto del comando persistido no cambia. `tool.execute.after`: mutar `output.output` in place cambia lo que recibe el modelo y lo que se persiste; para la tool de sub-agente es el texto final del sub-agente. La salida de bash en vivo (`metadata.output` streameado) esquiva este hook — el hueco aceptado en la decisión 3. `tool.execute.before`: la entrada persistida/mostrada en la TUI es siempre la original del modelo; sólo mutar `output.args` in place afecta la ejecución (no hacía falta acá). El estado de módulo de un plugin es compartido por toda sesión del proceso. El propio `engram.ts` ya tenía su `chat.message` (postea a `/prompts`) y su `tool.execute.after` (captura pasiva) y un `stripPrivateTags`.

**Qué se construyó.**

*Catálogo (dato, CORE).* `src/pegasus/content/security/credential-transport-catalog.json`, esquema `pegasus/credential-transport-catalog/v1`. Reglas: contexto de clave (una lista de nombres de clave case-insensitive, tolerante a `-`/`_` — `token`, `access_token`, `refresh_token`, `id_token`, `auth_token`, `api_key`/`apikey`, `secret`, `client_secret`, `clientkey`/`client_key`, `password`/`passwd`/`pwd`, `private_key` — con un patrón de valor de 8+ caracteres que descarta un placeholder ya sustituido); headers (`Authorization: Bearer|Basic <v>`, `X-Api-Key`/`api-key: <v>` — un header cuyo valor es JSON, como `X-Authorization: {...}`, no está en esta lista a propósito: lo resuelven las reglas de contexto de clave sobre el JSON interno, dejando `id` y otras claves no sensibles intactas); credenciales de URL (`scheme://user:password@host`); formatos conocidos (`sk-…`, `ghp_`/`gho_`/`ghu_`/`ghs_`/`github_pat_…`, `AKIA[0-9A-Z]{16}`, `xox[abprs]-…`, JWT, un bloque `-----BEGIN … PRIVATE KEY-----`); y el fallback explícito `<private>NOMBRE=valor</private>` / `<private>valor</private>`. Nunca detecta un hex de 40 u 64 caracteres bare, un UUID o un número — probado en `tests/test_credential_transport_content.py`.

*Adapter (OpenCode).* Sigue el precedente de `skill-registry.ts` + `pegasus-skill-registry.env`: un nuevo plugin, `assets/plugins/secret-transport.ts` (instalado como `pegasus-secret-transport.ts`), acompañado de un sidecar de datos que el adapter escribe al lado, `pegasus-secret-transport-catalog.json` — copia verbatim del catálogo del content core (`core.credential_transport.load_catalog_bytes`), nunca retipeado. El plugin mantiene un registro en memoria valor→`$PEGASUS_SECRET_<NOMBRE>` (el NOMBRE se deriva de la clave o del nombre de la regla, mayúsculas, cualquier corrida de caracteres no alfanuméricos se colapsa a un guión bajo — `clientKey` → `CLIENTKEY`, `client_secret` → `CLIENT_SECRET`, `github_token` → `GITHUB_TOKEN` —; colisiones entre nombres distintos se resuelven con `_2`, `_3`; el mismo valor siempre mapea al mismo nombre). `chat.message` detecta y sustituye en cada parte de texto, in place, y agrega una nota breve avisando qué variables reemplazan valores privados, que un comando de shell las expande, y que su valor nunca debe escribirse ni imprimirse — corre también sobre el brief de un sub-agente. `shell.env` expone cada `PEGASUS_SECRET_<NOMBRE>` registrado. `tool.execute.after` redacta cualquier valor ya registrado que reaparezca en `output.output` o en `output.metadata.output`. El plugin expone además una función de redacción de proceso completo en `globalThis` (`__CREDENTIAL_TRANSPORT_V1__`, sin la marca del producto: es plomería interna entre plugins, no una variable de wire con el modelo) para que otro plugin la llame.

*`engram.ts`.* Antes de postear a `/prompts` y a `/observations/passive`, llama a esa función global si está presente, además del `stripPrivateTags` que ya tenía — comentado como una divergencia mínima, en la línea de las de 7.1.0/7.2.0. Como la asignación al global ocurre al nivel de módulo (cuando OpenCode carga el plugin), no dentro de un hook, el orden de carga entre los dos plugins no importa: para cuando cualquiera de los dos hooks dispara, los dos módulos ya se cargaron. Probado en ambos órdenes por `tests/test_engram_credential_redaction.py`.

*Port/capability.* `CredentialTransportCapability` (`core/types.py`), cuatro booleanos —`detect_and_replace`, `inject_at_execution`, `redact_on_output`, `redact_before_memory`— y `credential_transport.capability_of(adapter)` en `core/credential_transport.py`, que resuelve por duck-typing: un adapter que nunca implementa `credential_transport()` obtiene los cuatro en `False`. Claude Code está registrado en este release (`ADAPTERS`, `src/pegasus/adapters/__init__.py`, soportado desde 6.0.0) y es exactamente el caso que ese default cubre: no implementa `credential_transport()`, así que `capability_of` le resuelve los cuatro en `False` sin una sola línea de código propia acá. `OwnArtifacts` de OpenCode gatea el archivo del plugin y su sidecar detrás de `capability_of(self).any`; `tests/test_credential_transport_port.py` prueba el caso negativo contra el adapter real de Claude Code —no un stand-in monkeypatcheado—, tanto llamando a `own_artifacts` directamente (no emite ninguno de los dos archivos; lo único que ese adapter emite es la clave `agent` de `settings.json` y la referencia generada de delegation-capabilities, confirmado leyendo su salida real) como con un `install --cli claudecode` real contra un home descartable.

*Reglas de contenido (CORE, ambient).* Una sección nueva en `system-prompt/AGENTS.md`, "Credential Transport", con tres párrafos: una credencial que la persona pega es suya para administrar — se usa para la tarea, nunca se aconseja rotarla/revocarla/regenerarla, nunca se rechaza usarla por haber aparecido en la conversación; cuando un valor fue reemplazado por una variable como `$PEGASUS_SECRET_TOKEN`, se usa ese nombre — un comando de shell la expande — y se pasa el nombre, nunca el valor, a cualquier brief, comando, archivo, escritura de memoria o respuesta ("cualquier brief" ya cubre el de un agente que se lance, sin restatearlo aparte); nunca se imprime una variable de credencial — nada de `echo`, nada de flag verboso que la vuelque. El archivo pasó de 1284 a 1385 palabras (+101) — siempre-activo, así que el costo se reporta acá. Ninguna nombra un CLI (verificado por `test_content_core_is_cli_agnostic.py`, que ya escanea este archivo). El párrafo sobre rotar/revocar/regenerar queda fijado como closed-world dentro de `system-prompt/`: `tests/test_credential_transport_content.py` prueba que ningún otro párrafo del system prompt siempre-activo toque ese tema — se descartó extender el closed-world a todo `content/`, porque una skill de dominio (`lazy-load-prompt-audit`) dice legítimamente "regenerar desde la fuente canónica" sobre una plantilla, un tema ajeno a una credencial del usuario.

**El hueco aceptado de la salida en vivo.** Un comando que imprime el valor de una credencial mientras corre (por ejemplo, un `curl -v` que vuelca headers, o un script que hace `echo $TOKEN`) lo deja en el historial de sesión y en la TUI antes de que `tool.execute.after` pueda redactar la salida final — ese hook corre una sola vez, al terminar la tool, nunca por cada línea de salida en streaming. No hay filtro de salida en vivo en este release, por decisión del usuario (decisión 3 arriba); la única mitigación es de contenido: la regla ambient nueva prohíbe imprimir una variable de credencial en primer lugar.

**Otro hueco aceptado, encontrado en revisión: un valor sin comillas que es puro texto de identificador, sin ningún dígito, no se detecta en el paso `key=value`/`key: value`.** El catálogo (`key_context.skip_unquoted_if`) hace que ese paso ignore, además de una llamada a función (`getToken()`), una ruta con punto (`process.env.X`, `this.token`) y una interpolación de shell o template (`$VAR`, `${VAR}`, `%(name)s`), cualquier valor sin comillas con forma de identificador que no tenga NINGÚN dígito (`accessToken`, `password`) — porque, sin esas cuatro exclusiones, el mismo paso corrompía código pegado: `const token = getToken()` terminaba como `const token = $PEGASUS_SECRET_TOKEN`. La consecuencia deliberada: `DB_PASSWORD=secretpass` (sin comillas, sin dígito) NO se detecta — sólo `<private>` lo cubre. `DB_PASSWORD=s3cr3tP4ss` (con al menos un dígito) sigue detectándose, igual que cualquier valor entre comillas (`password: "plainword"`), porque estar entre comillas es justamente lo que distingue un valor de un fragmento de código. Ver la sección correspondiente de MANUAL.md.

**Deudas:**

- Claude Code está registrado (ver arriba) pero no implementa `credential_transport()`, así que hoy declara las cuatro operaciones en `False` por el default del duck-typing, no por una decisión explícita tomada para este adapter. Si alguna vez se le agrega soporte real, hace falta evaluar cada operación por separado (ver el punto siguiente) y escribir `credential_transport()` con lo que efectivamente soporte; no hace falta tocar nada más de este mecanismo.
- Para esa evaluación futura: `UserPromptSubmit` no puede reescribir el prompt del usuario antes de que se persista (a diferencia de `chat.message` de OpenCode), así que la detección+reemplazo en la entrada no tiene dónde engancharse hoy con los hooks documentados; `PreToolUse` sí puede modificar el input de una tool, así que la inyección en ejecución y la redacción de salida podrían tener un análogo — evaluar cuando se construya soporte real, no ahora.
- OpenCode v2 es una línea propia, y esta viñeta decía algo inexacto sobre ella. Antes afirmaba que v2 trae una tool de bash con un TODO para `shell.env` («once V2 plugin hooks exist»). Ese TODO vive en el árbol 1.x (`core/src/tool/bash.ts`, en v1.18.34 y en `dev`). v2 ya tiene un hook `shell` / `create.before` (`packages/core/src/shell.ts:274`), así que migrar el transporte de credenciales ya no espera un hook. Lo que sí es cierto:
  - v2 es la v2.0.21 (el tag v2.0.18 del 25 de septiembre de 2026 era una anterior), con su propia rama `v2` y su propio paquete npm, `@opencode/cli`, divergida de `dev`, de la que sale la 1.x que se usa.
  - Renombra la tool de sub-agentes a `subagent` (ver 7.2.0).

  El 27 de septiembre de 2026 el usuario decidió empezar a prepararse para esa versión. Lo que rompería hoy en Pegasus, **leído del código y no corrido**:
  - los plugins necesitan un export por defecto `{id, setup}`;
  - `instructions` no se resuelve, así que `pegasus-AGENTS.md` quedaría inerte;
  - MCP en modo Code Mode es el default, y Pegasus deniega `execute`;
  - cambió la forma de la salida de la tool de sub-agentes;
  - `subagent_depth` pasó a `experimental.subagent_depth`, con default 1;
  - `apply_patch` ahora es `patch`.

  Lo que se puede preparar ya en 1.x, también por lectura de código: plugins con doble forma (la actual y `{id, setup}`), `experimental.subagent_depth`, y `mcp.servers.<id>` con `codemode: false`. Los hooks de plugins, los ids de tools, el formato de los agentes y los permisos siguen sin relevarse uno por uno.
- Los valores registrados se pierden cuando el proceso de OpenCode se reinicia, por diseño (decisión 2 arriba): no es un bug, es la superficie de vida elegida. Ver el MANUAL.md.

## 7.3.1: dos ajustes al catálogo de detección de credenciales

**El caso real que lo motivó.** El usuario pegó un curl real contra un servicio de obra social (valores acá siempre falsos). El plugin reemplazó `apiKey` pero dejó dos cosas en claro: `clientKey` (7 caracteres) sobrevivió porque el mínimo de 8 caracteres del catálogo se aplicaba parejo, sin distinguir si el valor estaba al lado de una clave sensible o no; y el valor del header `X-Aco-Joven-Signature` sobrevivió porque el catálogo sólo conocía nombres de header explícitos (`Authorization`, `X-Api-Key`) y un hex bare nunca se marca por forma sola (decisión 1 de 7.3.0).

**Los dos ajustes, vinculantes:**

1. **Mínimo de 4 caracteres, pero sólo al lado de una clave sensible.** `key_context.min_value_length` (nuevo, `4`) reemplaza al `min_value_length` general (`8`, sin cambios) para los tres pasos de contexto de clave del plugin — JSON `"key":"value"`, `key: "value"`/`key: 'value'` con clave sin comillas, y `key=value` sin comillas —, nunca para headers, credenciales de URL o formatos conocidos, que siguen exigiendo 8. Ese piso más bajo, aislado a la vecindad de una clave sensible, es lo que hace falta para no perder un `clientKey` de 7 caracteres sin convertir cualquier texto corto en sospechoso.
   Para que 4 caracteres no empiece a marcar relleno sin valor real, el catálogo suma `key_context.filler_skip_values` (una lista cerrada de palabras — `null`, `none`, `nil`, `true`, `false`, `undefined`, `empty`, `xxx`/`xxxx`, `todo`, `changeme`, `placeholder`, `redacted`, y la palabra literal `secret`, todas comparadas sin distinguir mayúsculas y como valor COMPLETO, nunca subcadena) y `key_context.filler_skip_patterns` (una corrida de `*`, generalizando el patrón de 3+ que ya traía `placeholder_patterns`). `isPlaceholder()` en el plugin ahora consulta las tres listas — la vieja (`placeholder_patterns`, valores ya sustituidos o interpolados) y las dos nuevas — antes de sustituir cualquier valor, en cualquier paso. Las exclusiones de código sin comillas de 7.3.0 (llamada a función, ruta con punto, variable de shell/template, identificador sin dígito) siguen intactas y sin cambios.
2. **Header por sufijo de nombre, no por lista cerrada.** El catálogo suma una regla de header nueva, `headers.sensitive_suffix_header`, con `header_name_suffixes` (`-Signature`, `-Token`, `-Key`, `-Secret`, case-insensitive) en vez de `header_names` fijo: cualquier header cuyo NOMBRE termine en uno de esos cuatro sufijos cuenta como secreto, sea cual sea ese nombre — `X-Aco-Joven-Signature`, `X-Auth-Token`, `X-Client-Key`, `X-Hub-Signature`. El plugin distingue esta forma de regla por la presencia de `header_name_suffixes` en vez de `header_names`, y en este caso el NOMBRE de la variable se deriva del propio nombre del header capturado (`$PEGASUS_SECRET_X_ACO_JOVEN_SIGNATURE`), no del `name` fijo de la regla como en `authorization`/`api_key_header`. Un header como `X-Signature-Version` no matchea: termina en `-Version`, no en `-Signature` — el sufijo se exige inmediato antes de los dos puntos, no en cualquier parte del nombre. Un header cuyo valor es JSON (como `X-Authorization: {...}` en 7.3.0) sigue cayendo a las reglas de contexto de clave sobre el JSON interno, sin cambios — esta regla nueva es sólo para el VALOR entero de un header, no para lo que hay adentro de un JSON. `signature` se agregó también a `key_context.keys`, para que `"signature": "…"` dentro de ese JSON interno se detecte igual que `token` o `clientKey`.
   - **Bloqueante encontrado en revisión, corregido en la misma entrega.** El sufijo, tal cual, no cubría la forma real del header de firma de webhook de GitHub, `X-Hub-Signature-256` — el mismo caso de uso que motivó la regla. La regla suma `allow_trailing_digit_segment: true`: el plugin, sólo cuando el flag está presente, arma el sufijo como `(?:-signature|-token|-key|-secret)(?:-\d+)?` — el sufijo, opcionalmente seguido de exactamente un segmento `-<dígitos>`. `X-Hub-Signature-256` y un `X-Signature-512` hipotético matchean; `X-Signature-Version` y `X-Api-Key-Version` siguen sin matchear, porque lo que sigue al sufijo ahí no son dígitos y el grupo opcional no puede alcanzar los dos puntos de ninguna manera.

**Otro hallazgo de revisión, corregido en la misma entrega: un `key:`/`key=` irrelevante que precede a un par sensible se lo tragaba entero.** En el paso `key=value`/`key: value` SIN COMILLAS (paso 8), el plugin corría antes sobre `String.replace` con una sola pasada global: cuando la clave capturada no era sensible (`note`, `Content-Type`), el intento de match igual consumía todo el tramo — clave irrelevante, separador, y el "valor" completo, que en textos reales suele ser otro `clave=valor` real (`note: password=<valor real>`, `Content-Type: password=<valor real>`, `Set-Cookie: token=<valor real>; Path=/`) — y como ese tramo entero quedaba consumido aunque el reemplazo se rechazara, el par sensible de adentro nunca tenía su propia oportunidad de matchear. El paso 8 ahora es un escaneo manual con `RegExp.exec` en un loop en vez de `String.replace`: cuando un intento se rechaza, el cursor de búsqueda (`re.lastIndex`) avanza sólo hasta el final de la CLAVE rechazada, no del match entero, así que el escaneo reintenta desde ahí mismo y encuentra el par sensible como su propio match independiente. De paso, `key_context.unquoted_value_pattern` ahora excluye también `;` (antes sólo excluía espacio, comillas, llaves, corchetes y coma) — sin esa exclusión, un valor de cookie como `token=<valor>; Path=/` se tragaba el `;` como parte del valor.

**Re-revisión: dos bloqueantes más y un riesgo de performance pre-existente, los tres corregidos en la misma entrega.**

1. **Bloqueante: una query string de URL perdía datos.** `?token=<valor>&page=2` se volvía `?token=$PEGASUS_SECRET_TOKEN` sin más — `&page=2` quedaba adentro del "valor" detectado, y se borraba con él. `key_context.unquoted_value_pattern` ahora excluye también `&` y `?` (sumados a la exclusión de `;` de arriba): el valor sin comillas se corta en el próximo separador de query string, no lo cruza.
2. **Bloqueante: el loop del paso 8 era O(n²).** `"a:b:c:d:".repeat(8000)` — cada candidato se rechaza, pero antes de esta corrección el escaneo del "valor" sin límite seguía hasta el final del string en cada intento; medido, ~5,7s en n=8000, ~4x por cada duplicación de n: cuadrático. Excluir `:` de `unquoted_value_pattern` (mismo cambio que el punto 1, misma lista) resuelve el caso medido: el valor ahora se corta en el próximo `:`, así que cada intento hace trabajo acotado. Pero excluir `:` no alcanza para el caso general — un `1MB` de `a` sin ningún separador en ningún lado sigue siendo vulnerable, no por el valor sino por la propia CLAVE: `\b(identificador)...` no tiene ancla real (`\b` no impide reintentar el mismo backtrack costoso en cada posición de una corrida larga sin separador). La clave del paso 7 y del paso 8, y el nombre de header del sufijo del punto 2 de arriba, cambian de `\b(...)` a un lookbehind negativo que sólo permite EMPEZAR un match donde el carácter anterior no es parte de la clase de continuación del identificador (`(?<![A-Za-z0-9_$-])`, o `(?<![A-Za-z0-9-])` para nombres de header) — así, ese backtrack costoso corre como máximo una vez por corrida contigua, no una vez por carácter adentro de ella, que es lo que lo volvía O(n²).
3. **Riesgo pre-existente de 7.3.0, corregido ahora porque este release toca esta misma zona:** `url_credentials.pattern` (`[a-zA-Z][a-zA-Z0-9+.-]*://...`) tenía la misma forma vulnerable — una clase repetida al inicio, sin ancla, seguida de un literal (`://`) que puede no aparecer nunca. Medido: ~2,6s con 32.000 caracteres de puro texto de "forma de scheme" sin `://` en ningún lado; una línea de 1&nbsp;MB con esa forma colgó más de 300s. Este plugin corre en cada mensaje de usuario y en cada brief, y el redactor global corre sobre el cuerpo de cada POST de engram (salida de un sub-agente) — un paste grande o una salida grande podían congelar OpenCode. Mismo fix que el punto 2: un lookbehind negativo (`(?<![A-Za-z0-9+.-])`) ancla dónde puede EMPEZAR un match, así el backtrack corre una vez por corrida, no una vez por carácter.
   Además, defensa en profundidad: un tope nuevo en el catálogo, `max_detect_bytes` (`262144`, 256&nbsp;KiB). Por encima del tope, `detectAndReplace()` se salta LOS OCHO pasos de detección enteros — la parte cara — y cae directo a `redactKnownValues()`, una búsqueda de substring exacta por cada valor YA registrado, lineal en el texto y en el tamaño (chico, de vida de proceso) del registro. Un valor nunca visto antes no se atrapa por esta vía si el texto supera el tope, pero nada de esto bloquea el mensaje — es la misma filosofía de "fail open" del resto del mecanismo, aplicada también al tiempo de ejecución, no sólo a los errores.

Medido antes/después con el mismo benchmark (`node --experimental-strip-types`, cinco corridas por caso): `"a:b:c:d:".repeat(8000)` bajó de ~5,7s a ~7ms; un texto de 32.000 caracteres de scheme sin `://` bajó de ~2,6s a ~1,5ms. Los cinco casos que el harness ahora prueba con cronómetro — `"a:b:c:d:".repeat(100000)`, 1&nbsp;MB de `a`, 1&nbsp;MB de caracteres de scheme (`abc+.-`), 1&nbsp;MB de blob base64, y una línea de 200&nbsp;KB con forma de JS minificado — terminan todos en menos de 30ms, muy por debajo del segundo exigido; varios de ellos superan el tope de 256&nbsp;KiB y ejercitan el camino barato de `redactKnownValues()`, así que el harness también prueba tamaños más chicos, por debajo del tope, para confirmar que el arreglo algebraico en sí (no sólo el tope) es lo que sostiene el tiempo lineal.

Probado extremo a extremo contra el curl real (con valores falsos) en `tests/test_secret_transport_plugin.py`, corriendo el plugin real con el catálogo real vía `tests/fixtures/secret_transport_harness.mjs` — mismo patrón que 7.3.0, con una sección de performance nueva (`results.performance`, con cronómetro por caso) y un caso que prueba que, por encima del tope, un valor ya registrado se sigue redactando. Toda la cobertura de detección anterior sigue pasando sin cambios.

## 7.3.2: aviso de variable sin valor, y una nota que nunca se duplica

**El caso real que lo motivó.** La persona copió un mensaje del historial de OpenCode. Ese texto ya había pasado por el plugin en un proceso anterior de OpenCode, así que traía `$PEGASUS_SECRET_APIKEY` más la nota de valores reemplazados. Lo pegó en un OpenCode recién reiniciado. Ese proceso nuevo reemplazó los valores que seguían en claro, agregó una SEGUNDA nota, y dejó `$PEGASUS_SECRET_APIKEY` sin registrar — el valor real vive sólo en la memoria del proceso que lo vio, así que un comando de shell en este proceso nuevo expande esa variable a vacío, y la API responde "unauthorized" por una razón que no se ve en ningún lado. El plugin ya era idempotente llamado dos veces sobre el mismo texto (verificado); el problema no era ahí — era que un texto ya procesado por OTRO proceso trae tokens que ESTE proceso nunca vio.

**Los dos cambios, vinculantes:**

1. **Aviso de variable desconocida.** En `chat.message`, después de detectar y reemplazar, el plugin escanea el texto completo del mensaje (todas sus partes de texto, unidas) buscando cada `$PEGASUS_SECRET_<NOMBRE>` cuyo NOMBRE este proceso no tiene registrado (`findUnknownVariableNames`, un regex sobre `usedNames`, el mismo registro que ya alimentaba `shell.env`). El placeholder literal `<NAME>` dentro del texto de la propia nota nunca se cuenta como desconocido: el regex exige al menos un carácter `[A-Z0-9_]` justo después de `SECRET_`, y `<` no es parte de esa clase — no hace falta una exclusión aparte. Si hay alguna variable desconocida, el mensaje lleva UN aviso claro: nombra las variables, dice que no tienen valor en esta sesión (reinicio de OpenCode, o texto copiado de una sesión anterior), dice que un comando de shell las expandiría a vacío, y pide pegar el valor real de nuevo. Una variable ya registrada, mencionada en prosa o en el brief de un sub-agente, nunca dispara el aviso.
2. **La nota nunca se duplica, y cuando aplican las dos cosas es UN solo bloque.** El plugin ahora arma el apéndice del mensaje comparando contra dos marcadores de texto (`REPLACED_VALUES_NOTE_MARKER`, `UNKNOWN_VARIABLE_WARNING_MARKER`) sobre el texto completo del mensaje antes de decidir qué agregar: la nota de valores reemplazados sólo se agrega si hubo un reemplazo en ESTE proceso y el mensaje todavía no la trae (de este proceso o de uno anterior, pegado); el aviso de variable desconocida sólo se agrega si el mensaje todavía no lo trae. Cuando aplican las dos, comparten un único separador `---`, no dos apéndices separados — `buildNoteBlock()` arma los párrafos que correspondan y los une con una sola línea en blanco entre ellos.

**Qué no cambió.** El catálogo de detección (`credential-transport-catalog.json`) es el mismo: esto es lógica de interpretación del plugin, no un dato nuevo de detección, así que no le toca nada al split hexagonal de 7.3.0. Sigue fallando abierto: un error en este camino nuevo nunca bloquea el mensaje (mismo `try/catch` de siempre alrededor de `chat.message`).

Probado en `tests/test_secret_transport_plugin.py` vía el mismo harness (`tests/fixtures/secret_transport_harness.mjs`), reproduciendo el caso real (un `X-Authorization` con `clientKey`/`signature` en claro más una nota vieja y una variable sin registrar pegadas del historial, con `shell.env` confirmando la ausencia de esa variable), un pegado fresco de valores (una nota, ningún aviso), una variable ya registrada mencionada en prosa (ni nota ni aviso), el mismo mensaje procesado dos veces (una nota y un aviso, ambas veces — nunca dos), y el brief de un sub-agente con una variable desconocida (lleva el aviso). Toda la cobertura de detección y performance anterior sigue pasando sin cambios.

### 7.3.0: tanda chica — la TUI ajusta texto en vez de cortarlo, una feature por-CLI se etiqueta como tal, y los directorios externos quedan permitidos por default en las dos CLIs

Tres cambios chicos, sin versión propia, agrupados porque ninguno merece su propia sección.

**Ajuste de línea (word wrap) en la TUI.** Antes, `app.draw()` (`src/pegasus/tui/app.py`) recortaba cualquier `Line` más ancha que la ventana real — `text[: room - column]` — sin aviso: la mitad de una oración simplemente desaparecía. Eso causó un mal diagnóstico real, porque alguien actuó sobre un mensaje cortado a la mitad. La capa pura (`view.py`, que nunca toca una terminal) ahora decide dónde parte una línea de prosa, antes de que `draw` la vea: `view._wrap_text(text, width)` corta por espacios, y sólo parte una palabra sola cuando esa palabra es más ancha que `width` — no hay otro corte posible. `view._wrap_lines` aplica esto a cada bloque de texto libre que una pantalla trae: la nota de un `Placeholder`, la prosa de un reporte (`cli.prose_for`), el prefacio del menú principal, encabezado/pie/vacío/trailer de una lista de elección (`_render_choices`).

Lo que **no** se ajusta, a propósito: la propia fila de un menú o de una lista de elección (`Entry`, cada ítem de `_render_choices`) sigue siendo exactamente una `Line`, porque `_visible_window` (el mecanismo de scroll que ya mostraba "N more above/below" para una lista larga) asume una fila por ítem — partirla rompería esa cuenta y la aritmética del cursor. Tampoco se ajustan el arte del wordmark, la barra de progreso, ni la línea del spinner en `render_busy`/`render_progress`: esta última es la barra de estado de una sola línea que el propio pedido de este cambio permite dejar truncada — se repinta a cada tick de la animación, así que reacomodarla en más de una fila la haría temblar cuadro a cuadro sin ganar nada, y `draw()` la sigue recortando igual que siempre (el mismo clip queda como red de seguridad defensiva para cualquier `Line` que, por lo que sea, todavía desborde la ventana). Cubierto en `tests/test_tui_view.py` (`WrapTextTest`, `NarrowWindowRenderingTest`, `ChoiceRowsNeverWrapTest`, más un caso por pantalla afectada) y sin cambios en `tests/test_tui_app.py::DrawSpanTest` (el clip de `draw` sigue probado tal cual).

**Una feature por-CLI se nombra como tal, en vez de fallar recién al entrar.** Inventario de qué depende de una capacidad de adapter: de los siete miembros de `Capability` (`core/types.py`) sólo `PER_AGENT_MODEL` difiere entre adapters registrados hoy (OpenCode `True`, Claude Code `False`) y tiene una superficie propia (`pegasus models`, la entrada `Configure models` de la TUI) — el resto (`skills`, `system_prompt`, `slash_commands`, `sub_agents`, `mcp`) lo declaran ambos en `True`, y `prompts` difiere pero es un detalle de render sin elección expuesta a la persona. `CredentialTransportCapability` (ver la sección de arriba) también difiere entre adapters, pero no tiene comando ni entrada de menú propia — es un artefacto que `install` agrega o no en silencio — así que no hay una fila que marcar "disabled": queda documentado acá como el caso donde la regla no aplica por falta de superficie, no por omisión.

Antes, elegir `Configure models` → elegir una CLI sin `per_agent_model` abría un `Placeholder` recién ahí, después de haber "entrado" a esa elección, y encima con una frase de implementación ("never declared support for per-agent models") que no le dice nada a la persona sobre *por qué*. Los dos problemas se resolvieron juntos.

*El motivo lo declara el adapter, no lo inventa la TUI.* `CapabilityManifest` (`core/types.py`) ganó un campo `reasons: dict[Capability, str]` y un método `reason_for(capability) -> str | None`, con la misma disciplina que ya tenía cada capacidad booleana: `__post_init__` rechaza un motivo para una capacidad que ese mismo manifest declara `True` (no puede haber un motivo para una ausencia que no existe). `adapters/claudecode/manifest.py` declara el suyo para `Capability.PER_AGENT_MODEL`: "Claude Code has no local model catalog to read; it resolves provider and model against its own API at run time, so no model can be assigned per agent there." — la causa real, no una reformulación de la condición booleana. `cli.per_agent_model_reason(adapter)` es la única función que lo lee: el motivo propio del adapter si lo declaró, o si no un fallback genérico armado sólo con `adapter.display_name` ("{display_name} does not support assigning a model per agent."), para un adapter futuro que no declare ninguno.

*Una sola voz, tres superficies.* `cli._require_per_agent_model` arma su rechazo con `per_agent_model_reason(adapter)`; `tui.session._models_screen` arma su `Placeholder` con la misma llamada; `tui.session.disabled_model_reasons()` la resuelve por adelantado para cada adapter sin la capacidad y se la entrega a `tui.navigator.models_menu` como `dict[str, str]` (CLI id → motivo ya resuelto) — la fila de esa CLI se marca `"... -- disabled: <motivo>"`, visible antes de elegirla, nunca un fallo recién al entrar. `navigator.py` no resuelve nada por su cuenta ni nombra una CLI por literal: sólo formatea la cadena que ya le llegó, la misma regla hexagonal que ya seguía `per_agent_model`/`CredentialTransportCapability` — `tests/test_tui_navigator.py::NoCliLiteralsInNavigatorTest` escanea el archivo fuente contra el nombre de cada adapter registrado para que eso quede pinneado, no sólo dicho. `disabled_reasons=None` (el default de todo llamador anterior a este cambio) no marca nada.

`pegasus models --help`, y ahora también `pegasus models set/unset/list --help` (cada subcomando arma el mismo sufijo con `cli._per_agent_model_suffix()`), nombran ahí mismo, dinámicamente, qué CLI la soporta (`cli._per_agent_model_display_names()`, derivado de `available()`), así que una CLI que sume o pierda la capacidad en otro release cambia sola el texto de ayuda, sin retipear nada. Cubierto en `tests/test_types.py::CapabilityManifestTest`, `tests/test_tui_navigator.py::ModelsMenuTest`/`NoCliLiteralsInNavigatorTest`, `tests/test_tui_session.py::DisabledModelReasonsTest` y `tests/test_cli_models.py::HelpNamesCapableClisTest`/`CapabilityRefusalTest`, todos derivados de `available()` en vez de nombrar "OpenCode"/"Claude Code" a mano, para que un tercer adapter quede cubierto el día que se registre.

*El bug de wrap bloqueante.* `_wrap_text` sólo partía por espacio, así que un texto con un salto de línea propio (por ejemplo `cli.unresolved_bindings_message`, que arma `"...:\n  {command}\n..."` y llega a un `Placeholder` a través de `session._mcp_selection_screen`/`_grant_mcp_screen`) podía terminar con el `\n` incrustado en medio de una palabra partida, y ese carácter crudo llegaba a `window.addstr` en `draw()` y corrompía la fila. La corrección quedó en `_wrap_lines`, no en `_wrap_text`: cada texto se parte primero por sus propios saltos de línea (`text.splitlines() or ("",)`, preservando una línea en blanco entre dos párrafos) y sólo entonces cada línea, ya sin `\n`, se envuelve por separado. Cubierto en `tests/test_tui_view.py::WrapLinesEmbeddedNewlineTest`, con el repro real de `cli.unresolved_bindings_message` incluido, no sólo un caso sintético.

**Directorios externos permitidos por default en Claude Code también, con el mismo piso que OpenCode.**

*La decisión, en palabras del usuario.* «no es una deuda, es una decisión que tomé en opencode y ahora tomo en claude code también, ambas igual». En OpenCode, un directorio externo al worktree del proyecto está permitido por default desde el 21 de septiembre de 2026 (ver la sección de arriba sobre `external_directory` y el bug de OpenCode `anomalyco/opencode#39112` que expuso, sin motivar, esa línea de base). La única excepción es un piso fijo — `.ssh`, `.aws`, `.credentials`, `.config/gh`, `secrets` — que gana la resolución del runtime pase lo que pase con la línea de base. Este release lleva la misma decisión, con el mismo piso, a Claude Code.

*El piso deja de estar escrito una sola vez, en el vocabulario de OpenCode.* Antes de este release, la constante que traduce los cinco directorios al comodín (`*/.ssh/*`, ...) que entiende el permiso `external_directory` de OpenCode (`adapters/opencode/render.py`) era el único lugar que sabía cuáles son esos cinco directorios — un dato CLI-agnóstico agazapado adentro de un adapter, la regla 2 de este documento en abstracto. `content.DENY_FLOOR_DIRECTORIES` (`core/content.py`) es ahora esa única lista, en su forma agnóstica (`.ssh`, `.aws`, `.credentials`, `secrets`, `.config/gh`, ese orden preservado porque la salida de OpenCode ya lo pinnea byte a byte); la constante de OpenCode se deriva de ella con una comprehension y no cambió una sola línea de su propia salida — `test_opencode_adapter.py`, `test_external_directory_deny_floor_docs.py` y `test_external_directory_deny_floor_shadow.py` siguen pasando sin tocar ellos mismos. `adapters/claudecode/render.py` traduce la misma lista a su propio vocabulario: `PERMISSIONS_DENY_FLOOR`.

*Los hechos medidos, en vivo contra un usuario descartable, el 27 de septiembre de 2026 (no supuestos desde la documentación de Claude Code).* En `~/.claude/settings.json`: `permissions.allow: ["Read(//**)", "Edit(//**)"]` (el `//` inicial ancla en la raíz del filesystem) hace que una lectura Y una escritura fuera del directorio de trabajo pasen sin preguntar — `Edit(...)` alcanza también a la tool Write, según la propia documentación de Claude Code, que dice además que una regla `Write(path)` nunca se consulta; por eso Pegasus no escribe ninguna. `permissions.deny` con `Read(//**/<dir>/**)` y `Edit(//**/<dir>/**)` por cada directorio del piso bloquea Read, Edit/Write, Y ADEMÁS un `cat` de Bash sobre esas rutas — verificado para `.ssh`, `.config/gh` (dos segmentos) y `secrets`. Sin las reglas de deny, Claude Code no protege `.ssh` por su cuenta: el piso depende enteramente de escribirlas. `permissions.additionalDirectories` no hace falta — sólo concede lectura, nunca escritura — y por eso Pegasus no lo escribe nunca, ni tampoco fija `defaultMode`.

*Las reglas exactas que Pegasus escribe, y el modelo de ownership.* `render.permission_artifacts` (`adapters/claudecode/render.py`) devuelve doce artefactos, uno por regla: dos para `PERMISSIONS_ALLOW` (`Read(//**)`, `Edit(//**)`) y diez para `PERMISSIONS_DENY_FLOOR` (`Read(...)`/`Edit(...)` por cada uno de los cinco directorios). Cada uno es un `ConfigKeyArtifact` cuyo `pointer` termina en `/-` — `/permissions/allow/-` o `/permissions/deny/-` — el mecanismo de *append* que este documento ya describe más arriba («La excepción: punteros que agregan a una lista», sección de journal) y que este codebase ya usaba para la instrucción del system prompt de OpenCode (`/instructions/-`) o sus servidores MCP (`/mcp/<id>`): un append se identifica por su propia huella (`target`, `pointer`, `digest`), nunca por posición ni por ser dueño de la lista entera, así que las entradas propias de la persona — presentes antes de instalar, o agregadas a mano después — sobreviven intactas a instalar, actualizar y desinstalar, y reinstalar/actualizar nunca duplica una regla. `doctor` reporta drift sobre estas doce entradas exactamente igual que sobre cualquier otro append ya existente (`planner.record_append_identity`, `cli._digest_of_config_key`): no hizo falta enseñarle nada nuevo sobre permisos. `own_artifacts` (`adapters/claudecode/adapter.py`) es donde se agregan, junto a la clave `agent` que ya escribía — esa clave queda intacta, no compartida por ningún pointer con lo nuevo.

*`pegasus directory grant`/`revoke` es dormido y honesto en las dos CLIs por igual, y ninguna de las dos se lee comparando un id.* En palabras del usuario, no es una excepción para Claude Code: «no es una deuda, es una decisión que tomé en opencode y ahora tomo en claude code también, ambas igual». Antes de este release eso era cierto para el comportamiento (las dos ya son default-allow) pero no para el reporte: OpenCode seguía diciendo `opencode: granted <ruta> to every agent.`, que suena a que el otorgamiento tuvo un efecto que la propia sección de arriba ya llama **dormido**; Claude Code decía lo mismo (`claudecode: granted <ruta> to every agent.`) sin renderizar nada en absoluto — un reporte falso, no sólo optimista.

La primera corrección fue de diseño, no de texto: `cli.directory_grant` calculaba antes `dormant = adapter.id != OPENCODE_CLI_ID`, un id de CLI comparado a mano dentro de un módulo compartido — exactamente la regla 2 de este documento rota en la práctica. `DirectoryGrantBehavior` (`core/types.py`), dos booleanos —`allowed_by_default` (si la línea de base de esta CLI ya permite salir del worktree sin preguntar, piso aparte) y `writes_own_entry` (si otorgar un directorio igual renderiza una regla propia en la configuración, o no escribe nada)— es ahora lo que cada adapter declara, con el mismo molde que `CapabilityManifest.reasons` ya usa para "por qué no": `CliAdapter.directory_grant_behavior()`, requerido sin gatear en ninguna `Capability` (`registry._check_directory_grant_behavior`, incondicional, con el mismo criterio que ya aplica a `own_artifacts`) porque `content.grant_directories` ya alcanza a todo adapter sin excepción. OpenCode declara `(True, True)`: su baseline ya es `"allow"`, y seguir escribiendo `f"{ruta}/*": "allow"` por agente sigue siendo la misma entrada dormida, no inútil, que la sección de arriba describe. Claude Code declara `(True, False)`: su propio `permissions.allow` ya cubre todo desde la raíz del filesystem (`//**`), sin un concepto por-directorio que otorgar pudiera escribir.

`_directory_prose` — el único resolver de este texto, para `--json` y para el reporte humano por igual, ya que la TUI no tiene pantalla propia de `directory grant` — lee esos dos booleanos, nunca `adapter.id`, y arma la frase honesta para cada combinación: OpenCode ahora dice «recorded `<ruta>`, and wrote `"<ruta>/*": "allow"` as its own permission entry. This changes nothing today: external directories are already allowed by default there, outside the fixed always-denied floor»; Claude Code dice «recorded `<ruta>`; nothing needed writing. This changes nothing today: [...]». Un adapter futuro cuya propia línea de base todavía preguntara primero declararía `allowed_by_default=False` y recuperaría sin más la frase vieja, «granted ... to every agent» — la rama sigue ahí, sin código muerto, porque nada hoy la ejercita pero un tercer adapter sí podría.

Una revisión independiente encontró que este mismo párrafo, en su primer corte, sólo movió la comparación por id en vez de sacarla: el aviso de ruta-bajo-el-piso seguía gateado por `if adapter.id == OPENCODE_CLI_ID`, y desde este release Claude Code también escribe su propio piso (`PERMISSIONS_DENY_FLOOR`, sección de arriba) donde deny le gana a allow exactamente igual — así que una ruta otorgada bajo `.ssh`, `.aws`, `.credentials`, `.config/gh` o `secrets` en Claude Code reportaba éxito limpio, la misma falsa promesa que esta sección entera existe para sacar. La corrección real fue derivar el predicado del piso de `content.DENY_FLOOR_DIRECTORIES` en vez de la sintaxis de ningún runtime — `content.deny_floor_shadows(path)` es una prueba de substring plana (`f"/{nombre}/" in f"{path}/"` para cada nombre del piso), no un port del `Wildcard.match` de OpenCode, porque ninguna sintaxis de comodín sobrevive a `validate_granted_directory`: un valor que llega hasta acá ya no puede contener `*`, `?` ni corchetes. `DirectoryGrantBehavior` ganó un tercer campo, `has_deny_floor`, con el mismo molde que los otros dos: cada adapter lo declara (`True` en las dos CLIs hoy), y `directory_grant` sólo pregunta el predicado cuando el adapter dice que tiene piso — nunca comparando `adapter.id`, ni siquiera para esto. `opencode_render_module` y `OPENCODE_CLI_ID` dejaron de importarse en `cli.py` por completo: no queda una sola comparación de id en `directory_grant` ni en `directory_revoke`, guardado por `tests/test_cli_directory_all_clis.py::NoAdapterIdComparisonDrivesTheReportTest`, que ahora prohíbe la comparación sin excepción (la primera versión de este guardián la toleraba explícitamente para el aviso de piso, que era justo el punto ciego que la revisión encontró) y trae además un caso derivado sobre `adapters.available()`: una ruta bajo cada uno de los cinco directorios del piso avisa en cada adapter que declara piso, no sólo en OpenCode.

Los tres literales `.ssh, .aws, .credentials, .config/gh, secrets` que `cli.py` repetía a mano en el docstring y en dos mensajes de prosa quedaron unificados en `_DENY_FLOOR_DESCRIPTION = ", ".join(content.DENY_FLOOR_DIRECTORIES)`, un único punto que no puede desincronizarse del núcleo porque nunca vuelve a retipear los nombres.

`directory revoke` ganó la misma honestidad que `grant` ya tenía: antes decía «revoked `<ruta>`.» sin importar qué CLI fuera, aun para Claude Code, donde nunca hubo una entrada propia que revocar. Ahora carga `writes_own_entry` (la misma declaración del adapter) junto con el resto del reporte, y `_directory_prose` elige entre «revoked `<ruta>`; its own permission entry was removed.» (OpenCode) y «`<ruta>` removed from the record; nothing was written to unwrite.» (Claude Code) — nunca comparando `adapter.id`. `directory grant`/`revoke` siguen validando la ruta y dejándola en el journal en las dos CLIs exactamente igual que antes; lo único que cambió es el texto. `tests/test_cli_directory_all_clis.py`, derivado de `adapters.available()` en vez de una lista de CLIs escrita a mano, prueba el texto de las dos para `grant` y `revoke`, que el reporte coincide con lo que cada adapter declara (no con su id), y que cada adapter con piso avisa sobre cada uno de sus cinco directorios.

*Nada quedó pendiente aparte.* El reporte falso de `directory grant` en Claude Code no tenía una fila propia en la tabla de deudas de este documento hasta ahora — se encontró y se cerró en la misma unidad de trabajo, siguiendo la convención de este proyecto de resolver un seguimiento no bloqueante en la unidad que ya lo toca, en vez de abrir una ronda de cierre aparte para volver sobre él después.

## 7.3.3: la sesión principal de Claude Code alcanza sus propios servidores MCP, `mcp grant` escribe de verdad, y el AGENTS.md deja de confundir ausencia con denegación

Tres defectos medidos en vivo, todos bajo Claude Code, todos cerrados en la misma unidad.

**Primero, la identidad de sesión.** La clave `agent` de `settings.json` fija qué agente corre como la sesión principal, y esa sesión medía cero herramientas MCP incluso con sus servidores conectados en `mcpServers:`: su `tools:` las filtraba. Un sub-agente no tiene el problema, porque alcanza las herramientas de sus propios servidores sin nada más — verificado antes y después de este cambio. Nombrar el servidor a nivel de servidor en `tools:` (`mcp__<clave>`) expone todas sus herramientas; medido con engram, 18 de 18. `mcp__<clave>__*` se comporta igual; `mcp__*`, el comodín completo, es un no-op silencioso y nunca se renderiza. `disallowedTools` sigue ganando sobre el comodín de servidor, sin cambios. El render ahora escribe un `mcp__<clave>` por cada servidor del propio `mcpServers:` del agente de identidad de sesión (`item.default`, es decir el agente que nombra `content.SESSION_STARTS_IN`), derivado de los mismos descriptores que ya arman ese `mcpServers:` — nunca una segunda lista de a mano — más `ToolSearch`, que resultó necesario. En una sesión interactiva con todos los servidores arriba, Claude Code difiere las 61 herramientas MCP y las carga a pedido a través de esa tool. Sin servidores concedidos, `tools:` no cambia. Un sub-agente no se toca: ya alcanzaba sus servidores sin esto, y agregarle la entrada sería un cambio que nadie pidió.

**Segundo, `mcp grant`/`mcp revoke`.** El reporte ya decía la verdad sobre Claude Code (`writes_per_agent_entry=False`), pero lo que describía seguía roto: `core/catalog.py` armaba el `mcp=` de `render_agent` sólo con `item.optional_mcp`, nunca con `item.granted_mcp`, así que un grant a una clave que la persona administra por su cuenta (`claude mcp add`) no escribía ninguna entrada `mcpServers:` en ningún archivo de agente. `core.catalog._mcp_for_agent` hila ahora las dos: para cada clave en `granted_mcp` sintetiza un `Mcp` sólo con `bound_to=clave` — sin descripción, cuerpo ni distribución propios, porque Pegasus no sabe nada de un servidor que no fetchea ni define — con la misma forma de referencia atada que `optional_mcp` ya produce para un servidor bindeado. `ClaudeCodeAdapter.mcp_grant_behavior().writes_per_agent_entry` pasa a `True`, y el reporte humano y JSON de `mcp grant`/`mcp revoke` dice lo mismo para las dos CLIs ahora, derivado siempre del adapter y nunca de comparar `adapter.id`. Si el grant cae sobre el agente de identidad de sesión, la primera mitad de esta unidad le agrega además su propio `mcp__<clave>`.

**La garantía dura de esta mitad: el render de OpenCode queda byte-idéntico.** Su propio `render_agent` ignora por completo el parámetro `mcp` y lee `item.granted_mcp` directo del `Agent` que ya tiene — así que agrandar la tupla que `catalog.render` le pasa no puede cambiar ni un byte de su salida. Probado dos veces: llamando a `render_agent` con la tupla vacía y con la nueva, bytes idénticos; y de punta a punta, reconstruyendo una instalación completa de OpenCode con la función que este cambio reemplazó reinstaurada por `mock.patch`, y comparando el árbol completo contra la instalación real — `tests/test_cli_mcp_all_clis.py::OpenCodeRenderIsByteIdenticalAcrossTheCatalogChangeTest`.

**Tercero, el `AGENTS.md` embarcado leía mal una ausencia.** En una prueba interactiva real, el orquestador de Claude Code no tenía las herramientas de engram — simplemente ausentes, con el runtime devolviendo `No such tool available` — y lo leyó como una denegación, citó la viñeta «Tell the two denials apart» y se negó a delegar en un sub-agente que sí tiene engram, una delegación legítima. También infirió, mal, que el sub-agente no tenía MCP a partir de su `tools:`, y propuso registrar el servidor por su cuenta con `claude mcp add`. La viñeta de denegación real queda intacta, palabra por palabra: sigue siendo cierto que una herramienta que el runtime niega cierra todos los caminos. Se agregó una viñeta nueva, inmediatamente después, que dice las cuatro cosas que faltaban: una herramienta ausente del propio toolset no es una denegación y no cierra nada por sí sola; delegar en un agente cuyo propio alcance sí la incluye es legítimo cuando la tarea lo pide; lo que un target de delegación puede alcanzar es lo que lista `delegation-capabilities.md`, nunca el `tools:` del target, que es un hecho distinto; e instalar o registrar un servidor por cuenta propia para tapar el hueco no es decisión del agente — corresponde decir qué falta y preguntar. Pinneada por `tests/test_tool_absence_is_not_a_denial.py`, que además sostiene el tema mundo-cerrado en todo el árbol de `system-prompt/` — la viñeta nueva es la única sentencia que puede tocarlo — y registra su raíz en `tests/fixtures/closed-world-vocabulary.json`. `tests/test_editing_reach_scope.py` sigue intacto y en verde: no se tocó una palabra de la viñeta que ya tenía.

**Confirmado después, en interactivo.** El mismo 27 de septiembre, el usuario repitió la prueba interactiva en el usuario descartable, con este build y Claude Code 2.1.283, y todos los servidores arriba. Encontró cuatro cosas:

- `/context` muestra «MCP tools · loaded on-demand · 61 tools · 0 tokens». El modo de diferido existe, y es el caso normal con estos servidores. Así que `ToolSearch` no es un seguro: es por donde el orquestador carga sus herramientas MCP, y sin él no llegaría a ninguna.
- El orquestador llamó a `mem_current_project` de engram.
- También llamó a `index_status` de cbm, y el error que devolvió era del propio cbm: todavía no había nada indexado.
- Le pidió a `sdd-propose` la misma llamada de engram y delegó sin negarse. Antes leyó la tabla de capacidades de delegación, como pide la viñeta nueva de `AGENTS.md`.

## 7.4.0: una regla de archivos sensibles, el aviso de lo que OpenCode carga de Claude Code, y lo que encontró la revisión

Una tanda de cuatro cambios de código (3ab4b1f, b93734c, b591bdf, b107579) y el arreglo de lo que una revisión en contexto limpio encontró en ellos. No se subió la versión: esta sección registra las decisiones.

**Decisiones.**

1. **Regla de archivos sensibles en el contenido neutro.** `## Sensitive Files` en `system-prompt/AGENTS.md`, con párrafos fijados por test y sin clasificadores de negación. Cada agente la recibe con el prompt; sólo un agente que no lo cargue la necesita en el brief. No concede nada: la única salida es el permiso explícito de la persona para ese archivo.
2. **Lo que una CLI lee de otra se declara en el puerto.** `CliAdapter.foreign_loads()` devuelve `ForeignLoad`, y el núcleo lo evalúa y redacta sin comparar ids de adapter. `doctor` y `install`/`update` usan el mismo texto. Sólo hay existencia y conteos; ningún archivo se abre.
3. **Las variables se leen como las lee OpenCode.** Según el código de OpenCode (Effect 4 beta, `Config.boolean` con default `false`): `true`/`yes`/`on`/`1`/`y` son verdaderos, `false`/`no`/`off`/`0`/`n` falsos, mayúsculas distinguidas, y cualquier otro valor seteado es un error de configuración, no un falso. Pegasus lo copia, y ante un valor que OpenCode no acepta lo dice en el aviso. Un valor vacío se trata como no seteado, porque no se verificó cómo lo lee OpenCode. A `foreign_loads` se le sumó `OPENCODE_DISABLE_EXTERNAL_SKILLS` (`runtime-flags.ts:21`, usada en `skill/index.ts:186`), que también saltea `~/.claude/skills`.
4. **El conteo de skills es acotado, y lo dice.** El puerto de filesystem no resuelve rutas reales, así que no hay conjunto de visitados: un symlink de directorio se sigue sólo si cuelga directo de la raíz de skills, y sólo cuentan los archivos regulares llamados `SKILL.md`. Un ciclo suma una pasada extra y no crece de forma exponencial. A cambio puede contar de menos respecto del glob de OpenCode.
5. **Guardia contra rutas absolutas de la máquina en los tests** (`tests/test_no_real_host_paths_in_tests.py`, 3ab4b1f; no tenía fila en las deudas). Se derivan en ejecución el HOME y la raíz del repo; la raíz temporal del runtime y la forma de un scratchpad con UUID son los únicos patrones estáticos. La revisión la ajustó: no marca el HOME si es uno de los ficticios que los tests usan a propósito (`probe`, `me`, `u`, `x`, `person`, `someone`, `one`, `two`) ni uno demasiado genérico; el patrón de la raíz temporal exige contexto de ruta, así que un id de modelo como `claude-3-5-sonnet` no se marca; y sin `git` o sin checkout, el test se saltea en vez de fallar.
6. **El instalador** deja de bajar dentro de `$(...)` y nombra el directorio temporal antes de armar el `trap` (b107579). Ver más abajo lo que no se pudo probar.
7. **Vocabulario cerrado.** `CRAFT_RULE_SUBJECT` cubre ahora `openspec config` y `project config`, sin volver a la palabra `config` sola.
8. **El gotcha de node con nvm, resuelto sólo como documentación** (`MANUAL.md`, «Un MCP de npm que no conecta con Node de nvm»; no tenía fila en las deudas): un MCP de npm necesita `node` en el `PATH` del proceso que lanza la CLI, y con nvm eso sólo pasa en shells que cargaron nvm. Pegasus no cambia nada al respecto.

**Un defecto real del plugin de engram, encontrado en la revisión.** El plugin excluía las tools propias de engram de los contadores y de `ensureSession` con una lista de ids sin prefijo (`mem_save`, `mem_search`, …), pero OpenCode 1.x reporta una tool MCP como `<clave del servidor>_<tool>`, o sea `engram_mem_*`. En la base de la instalación viva hay 9338 llamadas `engram_mem_save` y ninguna `mem_save`, así que la exclusión no coincidió nunca. Ahora se compara también sin un `engram_` inicial, y se conservan los ids sin prefijo por si el servidor se registra con otra clave. Lo cubre `EngramPluginPassiveCaptureNodeTest.test_engram_own_tools_return_before_the_session_is_registered`, con el harness de node: una llamada a `engram_mem_save` sobre una sesión nueva no registra ninguna sesión, y `read` sobre otra sí. Contra el plugin anterior, ese caso falla. `toolCounts` se escribe y nunca se lee; se dejó como está, porque sacarlo toca tres sitios que esta unidad no necesitaba.

**Lo que no se verificó.**

- **El arreglo del instalador no tiene una prueba que falle contra el instalador anterior.** El test de humo pasó 100 de 100 contra `f33fbcc`; se probó además un disparador acotado, un stub de curl que lee su propio `SigBlk`, y dio vacío en los dos scripts, porque la máscara bloqueada sólo existe en una ventana de microsegundos antes del `exec`. El arreglo descansa en el comportamiento documentado de la máscara de bash. El 7-8% medido antes forzaba la señal en otro instante.
- **OpenCode con un valor inválido** (`ConfigError` según el código de Effect): leído, no corrido en un OpenCode vivo. Tampoco se corrió OpenCode para ver que cargue `~/.claude`; está verificado contra el código fuente de v1.18.32.
- **El resumen de lo que rompe OpenCode v2** (en las deudas de 7.3.0) es lectura de código, sin ejecutar.

## 7.5.0: entrega en paralelo

Un procedimiento nuevo para el orquestador, `skills/_shared/parallel-delivery.md`, que se carga sólo cuando un fan-out tiene escritores. Se alcanza desde dos punteros: el del cuerpo del orquestador (agregado tras la segunda corrida en vivo, ver abajo) y el de «Writers in parallel» de `sub-delegation-criterion.md`; ningún otro cuerpo siempre cargado lo nombra. No se subió la versión: esta sección registra las decisiones.

**El patrón y de dónde sale.** Lo vio funcionar el dueño del producto en uso real y pidió que Pegasus lo siga: clasificar el trabajo pendiente, repartirlo por propiedad de archivos, un worktree por escritor, lanzar todo en un mensaje, integrar con `cherry-pick`, correr la suite integrada, revisar con contexto limpio, un único escritor de arreglos y cierre a cargo del coordinador. El procedimiento es genérico: no trae los pasos de release ni de transporte de este proyecto. Es para varias unidades genuinamente independientes; una sola unidad chica sigue inline por las reglas de siempre.

**Las cuatro decisiones de la persona, tal como se tomaron.**

1. **Los escritores commitean en local.** Cada unidad que escribe hace UN commit local en la rama de su propio worktree, nunca hace push y no lleva atribución de IA ni de herramienta. El coordinador integra con `git cherry-pick` y comprueba con `git cherry <rama de integración> <rama>` que cada commit entró (sólo en picks limpios) antes de retirar el worktree y la rama. Esto reemplaza el «nothing committed» de `sub-delegation-criterion.md`.
2. **El coordinador corre la suite integrada.** Una corrida completa sobre el árbol integrado, hecha por él: un solo comando, la salida redirigida a un archivo, y leer la cola; y comprueba que la cuenta de tests cierra. Es una excepción a «ejecutar pruebas: delegar», y en el orquestador es la menor reescritura posible de esa viñeta. `ORCHESTRATOR_WORD_CEILING` subió de 1420 a 1433, exactamente las 13 palabras agregadas, con el motivo en el comentario del test.
3. **Los worktrees viven fuera del repositorio, igual en las dos CLIs.** Los crea el coordinador con `git worktree add -b <rama> <ruta> <base>`, sin apoyarse en el aislamiento propio de ninguna CLI, que puede ponerlos dentro del repo. La ruta es `${XDG_STATE_HOME:-$HOME/.local/state}/agent-worktrees/<repo>-<hash corto del toplevel>/<run-id>/<unidad>`; el nombre del directorio no nombra ningún producto porque un cuerpo de contenido sólo puede usar `{{skills_root}}`. Nunca bajo un nombre del piso de denegación, `git worktree prune` al empezar cada corrida, y nunca se copian archivos sensibles a un worktree.
4. **Avance por unidad.** Cuando la CLI entrega los resultados de a uno, una línea corta por unidad terminada y después el informe consolidado; cuando llegan todos juntos, sólo el consolidado. Enmienda el «report as one» del criterio.

**Lo que se leyó de las CLIs (código fuente y documentación, no se corrió nada en vivo).**

- OpenCode 1.18.x (código de v1.18.32 y v1.18.34): varias llamadas `task` en un mensaje corren concurrentes; `task` no tiene parámetro de directorio ni de aislamiento, y el modo en segundo plano es experimental y sólo se activa con una variable de entorno, no con `opencode.json`. El servicio de worktrees existe pero es del espacio de trabajo de escritorio, no de los sub-agentes. Un hijo trabaja en otro directorio por convención: `workdir` en bash y rutas absolutas.
- Claude Code 2.1.287: varias llamadas `Agent` en un mensaje corren concurrentes (tope 20 por defecto); `isolation: "worktree"` pone el worktree en `<repo>/.claude/worktrees/`, que sólo un hook `WorktreeCreate` puede mover. En modo fork interactivo todo sub-agente corre en segundo plano.
- Por eso el procedimiento emula lo mismo en las dos: el coordinador crea el worktree y cada escritor trabaja con rutas absolutas.

**Lo que no se verificó.** Se ejercitó en vivo en Claude Code `-p` (cuatro corridas) y en OpenCode (una corrida interactiva de la persona); no se midieron la ruta de una unidad fallida, la de un conflicto ni una corrida abortada. Las diez incertidumbres concretas tienen su fila en las deudas sin unidad asignada.

**Corrección tras la revisión de 3abb55e.** Una revisión en contexto fresco confirmó huecos del procedimiento y se cerraron en un commit posterior, sin subir la versión. Un `git cherry-pick` resuelto a mano deja a `git cherry` imprimiendo `+`, así que la compuerta nunca pasaría: ante un conflicto entre unidades estrictamente disjuntas la partición estaba mal, y el procedimiento hace `git cherry-pick --abort`, para y avisa; la compuerta rige para picks limpios y un pick resuelto por decisión de la persona se verifica por diff. Además: árbol limpio antes de lanzar (sin `stash`), definición concreta de `<run-id>` y de la rama, el comando del hash corto, la limpieza tras una corrida abortada, unidades que fallan, el entorno del worktree, el mínimo de dos unidades, revisión y arreglo proporcionales, y el orden del cierre. El techo de palabras del procedimiento subió de 718 a 1124. El criterio de sub-delegación no cambió: conserva «independently mergeable» y el procedimiento dice que, en una entrega bajo él, las unidades son estrictamente disjuntas. Lo que ningún permiso impide (el push de los hijos) está en la fila de deuda, no escondido en el texto.

**Evidencia de una corrida en vivo (Claude Code `-p`, 2026-10-02).** (a) Los tres intentos de push del coordinador fueron denegados por las reglas de `permissions.ask`, incluso con entradas en `--allowedTools`, y las referencias del origen bare no cambiaron. (b) El compuesto `cd <dir> && git status --short && ...` se denegó mientras `git status --short` solo pasó: por eso el procedimiento exige `git -C <ruta absoluta> ...` en todo comando de git, del coordinador y de los escritores, y nunca encadena `cd` con git; los demás comandos usan el parámetro de directorio de trabajo de la CLI o un único `cd <ruta> && <prueba>` sin git. (c) Con dos ediciones chicas el orquestador trabajó inline bajo el Direct Work Threshold, correctamente: el procedimiento en sí todavía no se ejercitó. Un hallazgo de esa corrida: `git * push *` también preguntaba por un commit cuyo mensaje decía «push», lo que se resolvió haciendo que los escritores lean el mensaje de un archivo (`commit -F`).

**Un `git push` de un subagente pide confirmación.** Decisión de la persona, tal como se tomó: «un `git push` de un subagente debe pedir confirmación, en las dos CLIs»; el coordinador, el agente primario de la sesión, no cambia donde la CLI lo permite. Un bloqueo total se rechazó porque a veces la persona le pide a un agente que suba. Una revisión en contexto fresco había comprobado que ningún permiso renderizado lo impedía (en OpenCode todo agente tenía `"bash": "allow"` sin patrones; Claude Code no tenía regla de Bash alguna).

- **OpenCode** (v1.18.32; v1.18.34 es idéntico en estos archivos). Todo agente `mode: subagent` con `bash` lo recibe como un mapa de patrones: `"*": "allow"` y después `git push` más los `gh` que escriben hacia afuera, cada uno en su forma simple, con prefijo de entorno y con ruta absoluta del binario (`SUBAGENT_BASH_PERMISSION` en `adapters/opencode/render.py`; la ampliación está en la sección «7.6.0»); los primarios (`pegasus-orchestrator`, `king-pegasus`) siguen con `"allow"` plano. Semántica leída en el código: `util/wildcard.ts:3-19` (`*` es `.*`, coincidencia anclada, y un ` *` final hace opcional la cola, así que `git push *` coincide con `git push` y con `git push origin main`); `permission/index.ts:28-37` (`evaluate` toma la última regla que coincide, por eso el `"*"` va primero); `tool/shell.ts:123-125` y `:408` (la orden se parsea con tree-sitter y se pregunta una vez con un patrón por nodo `command`, de modo que `cd x && git push`, `a; git push` y `$(git push)` se revisan cada uno por su texto), y `permission/index.ts:73-83` (basta un `ask` entre los patrones para que toda la llamada pregunte). `git -C dir push` y `git -c k=v push` coinciden con el segundo patrón.
- **Claude Code** (https://code.claude.com/docs/en/permissions, secciones «Wildcard patterns», «Compound commands» y «What a Bash rule doesn't match»). Sus permisos son por sesión, no por agente: el frontmatter de un agente sólo puede conceder herramientas (`tools:`) o quitarlas (`disallowedTools:`), nunca «preguntar». Se agregan a `permissions.ask` de `settings.json`, como `ConfigKeyArtifact` de sólo agregar (`PERMISSIONS_ASK` en `adapters/claudecode/render.py`), `Bash(git push *)`, `Bash(git * push *)` y `Bash(git * push)`, así que las entradas propias de la persona sobreviven a install, update y uninstall. La forma con espacio es la que la propia CLI escribe; `:*` es una grafía equivalente sólo al final. Las reglas de `ask` se aplican si cualquier subcomando de una orden compuesta coincide. **Límite de la CLI:** por ser por sesión, también le pide confirmación al coordinador.
- **Qué sigue sin atraparse**, en las dos: alias, scripts propios, un push dentro de `sh -c '...'` o `eval` y, entonces, los `gh` con banderas globales antes del subcomando. Cuando se tomó esta decisión tampoco se atrapaban una ruta absoluta al binario (`/usr/bin/git push`), `FOO=1 git push` en OpenCode (el texto del nodo de comando empieza con la asignación, así que ningún patrón anclado coincidía) ni los `gh` que escriben; la sección «7.6.0» cubre esas tres. Los patrones con comodín en medio también preguntan por cualquier orden de git cuyos argumentos contengan la palabra (`git log --grep push x`, `git checkout push`): un falso positivo, nunca una omisión. Los commits quedan protegidos porque el procedimiento hace que cada escritor commitee con `git -C <worktree> commit -F <archivo de mensaje>`, de modo que el texto del mensaje nunca llega a la línea de comandos (con `-m "no hacer push"` el patrón preguntaría). El archivo del mensaje vive fuera del worktree, en `<raíz>/<corrida>/<unidad>.msg`, y se borra tras el commit. En OpenCode, además, un subagente de profundidad dos o mayor que dispare el `ask` queda esperando un aviso que ninguna vista muestra (el mismo defecto #39112 que llevó a `external_directory` a `"allow"`); a profundidad uno el aviso aparece en la sesión raíz, cosa que se leyó del código fuente y no se midió.
- No se agregó ninguna declaración al puerto: nada del código compartido necesita leer cómo se guarda el push.

**Segunda corrida en vivo (Claude Code, 2026-10-02) y su arreglo.** Se le dieron al orquestador tres trabajos de escritura genuinamente independientes. (a) El fan-out ocurrió: lanzó tres escritores en un mismo mensaje. (b) No leyó el criterio ni el procedimiento, y usó el aislamiento de worktree propio de la herramienta `Agent`, que cae dentro del repo, en `.claude/worktrees`, justo lo que el procedimiento prohíbe; sus briefs no llevaban ruta de worktree, ni `git -C`, ni `commit -F`. (c) Los compuestos `git commit -m` de los escritores se denegaron en `-p`, así que no se entregó nada. Conclusión: la cadena lazy (cuerpo, criterio, procedimiento) no se dispara, porque el puntero que sólo vive en el criterio no se alcanza. El arreglo: una oración en el cuerpo siempre cargado del orquestador, junto a la viñeta del lanzamiento en paralelo, que manda a leer `parallel-delivery.md` antes de lanzar dos o más sub-agentes que escriben y prohíbe el aislamiento de worktree propio de cualquier CLI. Esto revierte la decisión anterior de no poner ningún puntero en el cuerpo del orquestador, por esta evidencia; el techo de palabras del cuerpo subió exactamente las 22 palabras de la oración, y `ProcedureIsLazyTest` ahora fija que sólo dos lugares nombran el procedimiento: el orquestador, una vez, y el criterio, una vez. Queda pendiente una tercera corrida en vivo que confirme que el orquestador ahora lo lee.

**Tercera corrida en vivo (Claude Code `-p`, 2026-10-02) y su arreglo.** Esta vez el orquestador llegó al procedimiento y lo siguió hasta el lanzamiento, pero la entrega no se completó, por tres resultados. (a) Sus propios comandos para armar la raíz, con `${XDG_STATE_HOME:-...}` y `$(...)`, se denegaron («Contains expansion»); los reintentó por pasos y no se bloqueó. (b) Cada uno de los tres escritores recibió la prueba prescrita `cd <worktree> && <prueba> > <archivo>` y las tres se denegaron: ningún escritor corrió pruebas ni hizo commit, y el coordinador se detuvo a pedir confirmación. (c) Los briefs de los escritores omitieron el párrafo listo para pegar del esquema del informe. Una medición del 2-10-2026, con una lista de comandos permitidos, dejó las formas tal como se midieron: `cd <dir> && <comando> > <archivo>` se deniega siempre, con el destino dentro o fuera del directorio, y `--add-dir` no lo cambia; sin `cd`, con rutas absolutas y redirección, pasa (por ejemplo `python3 -m unittest discover -s <WT>/tests -t <WT> -q > <ROOT>/<unidad>-tests.txt 2>&1`); `${VAR:-valor}` («Contains expansion»), `$(...)` («Contains command_substitution») y `"$(...)"` se deniegan por no poder analizarse; pasan los comandos simples sueltos `date -u +%Y%m%dT%H%M%SZ`, `head -c3 /dev/urandom | od -An -tx1`, `git -C <repo> rev-parse --show-toplevel`, `printf %s <ruta> | sha1sum` y `git -C <worktree> status --porcelain`; `printenv HOME` sólo pasa si la persona lo permite; y la herramienta de escritura de archivos puede crear `<raíz>/<unidad>.msg` fuera del worktree.

*El arreglo.* `parallel-delivery.md` suma una regla general, dicha una vez y válida para el coordinador y los escritores: ningún comando contiene `$(...)` ni `${...}`, y ninguno encadena `cd` con una redirección; cada valor se calcula en su propio comando simple y el resultado literal se escribe en el siguiente, porque un sistema de permisos sólo puede juzgar un comando que puede leer. El paso 4 arma el directorio de estado con `printenv XDG_STATE_HOME` (o `<home>/.local/state` con `printenv HOME` si no imprime nada), el run-id con `date` y `head ... | od` en dos comandos que el coordinador une, y el hash con `git -C <checkout principal> rev-parse --show-toplevel` y `printf %s <ruta> | sha1sum`; la raíz queda como ruta literal. El paso 5 manda correr las pruebas con el parámetro de directorio de trabajo de la CLI o, si no lo tiene, con las opciones de ruta del propio corredor y rutas absolutas, con la salida en `<raíz>/<run-id>/<unidad>-tests.txt`; el mensaje de commit se escribe con la herramienta de archivos en `<raíz>/<run-id>/<unidad>.msg`, luego `git -C <worktree> commit -F <esa ruta>` y después se borra el archivo; y el coordinador copia el esquema del informe en cada brief textualmente, con el párrafo listo para pegar. Si un comando se deniega, el agente se detiene, informa cuál y por qué, y nunca lo rodea; el informe del escritor y el del coordinador listan sus denegaciones. `PARALLEL_DELIVERY_WORD_CEILING` subió de 1333 a 1517, exactamente lo agregado. Los tests fijan cada una de esas cláusulas y comprueban que el procedimiento no prescribe ningún `$(` ni `${`. Pendiente: una cuarta corrida en vivo con las formas nuevas.

**Cuarta corrida en vivo (Claude Code `-p`, 2026-10-02).** El procedimiento corrió de punta a punta. Los valores se calcularon con comandos simples y ninguno de los 53 comandos de Bash tuvo `$(`, `${` ni un `cd` con redirección. Los tres escritores se lanzaron en un solo mensaje, sin una sola denegación de escritor; los commits usaron `-F` y no llevaron atribución. Siguió cherry-pick, luego la compuerta de `git cherry` y después la limpieza. La corrida de la suite del coordinador dio 69 pruebas, igual a la suma de la base más las unidades, y hubo una línea de avance por unidad. El push quedó retenido a la espera de confirmación y el origen no cambió. Quedaron dos huecos. (1) No se lanzó ningún revisor y no se dio razón: el diff integrado era de unas 450 líneas en tres módulos nuevos, y el paso 10 dejaba omitirlo en silencio. Arreglo: el informe del coordinador dice si hubo revisión y, si no la hubo, por qué (un diff trivial, y qué lo hizo trivial); un diff que agrega módulos o lógica nuevos no es trivial. (2) El directorio de la corrida `<raíz>/<run-id>/` quedó con los archivos de salida de las pruebas (`<unidad>-tests.txt` y la salida de la suite integrada); los `.msg` sí se habían borrado. Arreglo: en la limpieza del paso 8, una vez que los worktrees y las ramas desaparecieron, se borra ese directorio y sus archivos; los de una unidad fallida se conservan junto con su worktree y el informe los nombra. `PARALLEL_DELIVERY_WORD_CEILING` subió de 1517 a 1580, exactamente las 63 palabras agregadas, y los tests fijan las dos cláusulas. Una observación sin arreglo: el primer comando del coordinador, antes de leer el procedimiento, seguía siendo un `cd && git` que se denegó y se reintentó con `git -C`; es inofensivo.

**Quinta corrida en vivo (OpenCode 1.18.34, 2026-10-02).** La hizo la persona, con GPT-6 Astra, sobre la compilación de c3fd0c2, y la entrega se completó de punta a punta. El orquestador leyó el procedimiento después de resolver la ruta de FTD. La comprobación de árbol limpio, con los pathspecs sensibles excluidos, se detuvo en `.atl/` y preguntó. Los valores se calcularon con comandos simples. Los worktrees quedaron en `~/.local/state/agent-worktrees/<repo>-<hash>/<run-id>/<unidad>`. Hubo tres implementadores; dos se detuvieron porque `python` no existía, sólo `python3`, y el coordinador los retomó. Siguieron la verificación de aislamiento, el cherry-pick en el orden indicado y `git cherry`. La suite del coordinador dio 39 pruebas, igual a la suma anunciada. Corrió una revisión proporcional porque había lógica nueva: encontró un `OverflowError` y se aplicó un único fix-up. Los commits usaron `-F` y no llevaron ninguna atribución. Se borraron los worktrees y las ramas. El push quedó retenido a la espera de la confirmación de la persona y el origen no cambió. Además, el orquestador guardó tres observaciones sobre el repositorio de prueba en engram; se borraron. Quedaron dos huecos. (1) `.atl/` frena la comprobación de árbol limpio en todo repositorio: el plugin propio de Pegasus escribe `.atl/skill-registry.md` al iniciar la sesión y, salvo que el proyecto lo ignore, `git status` muestra `?? .atl/`; el coordinador se detuvo y preguntó, que es lo correcto, pero pasaría en cada corrida. Arreglo, por decisión de la persona: el escritor del registro (`skill_registry.py`) agrega `.atl/` a `.git/info/exclude` cada vez que escribe el registro dentro de un repositorio git; nunca a `.gitignore`; la ruta se resuelve con `git -C <raíz> rev-parse --git-path info/exclude`, de modo que sirve en un worktree enlazado, y sin `git` se cubre el caso de un `.git` que es directorio; es idempotente (no agrega la línea si alguna ya ignora `.atl` o `.atl/`), crea `info/` si falta, fuera de un repositorio no hace nada y ante cualquier error avisa a lo sumo una vez por stderr sin afectar el registro. `sdd-init` y `_shared/skill-resolver.md` suman una instrucción corta equivalente para el agente que arma el registro, y el manual de OpenCode lo dice en una frase. (2) El directorio de la corrida seguía sin borrarse en las dos CLIs: los modelos se saltaban la frase del paso 8 y quedaban los `*-tests.txt`, la salida de la suite integrada y hasta los `.msg` del propio coordinador. Arreglo: es un comando concreto dentro de la secuencia de limpieza, `rm -r <raíz>/<run-id>` con la ruta literal, justo después de `git -C <checkout principal> worktree prune`, y se aclara que los archivos de mensaje de los fix-up del coordinador viven ahí y se van con él; los de una unidad fallida se conservan. `PARALLEL_DELIVERY_WORD_CEILING` subió de 1580 a 1606, exactamente las 26 palabras agregadas. Revisión final: el `rm -r` de la limpieza corre sólo si todas las unidades se integraron y no quedó ningún worktree ni rama, y tras comprobar que `<raíz>` y el run-id no están vacíos y son exactamente los literales registrados, de modo que una unidad fallida conserva su worktree y el directorio de la corrida; si `printenv HOME` no imprime nada se pide el directorio de estado a la persona; y el escritor del registro ejecuta `git rev-parse` sin `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` ni `GIT_COMMON_DIR` del entorno, porque `GIT_DIR` mandaba `.atl/` al exclude de otro repositorio; `PARALLEL_DELIVERY_WORD_CEILING` subió de 1606 a 1656, exactamente las 50 palabras agregadas.

## 7.6.0: piso de permisos, la entrega en paralelo en sus caminos de fallo, y OpenCode 2 en espera

Una release puede cambiarle el nombre. Registra cinco cosas.

1. **Una fuga de los tests.** Los tests de inyección del instalador armaban su `--bin-dir` hostil bajo un `/tmp` fijo; el instalador creaba ese directorio y cada corrida de la suite dejaba cuatro en `/tmp`. Ahora se arma dentro del directorio temporal del propio test, que se borra solo (2247d1c).

2. **Un piso de permisos para archivos sensibles (e5414d1).** La regla `## Sensitive Files` de 7.4.0 estaba sólo en el prompt; ahora además se hace cumplir por debajo del prompt.
   - **OpenCode.** `read` y `edit` (`edit` también gobierna `write` y `apply_patch`) se renderizan como `{"*": "allow", <piso>}`. Un agente `mode: primary` recibe `"ask"`; uno `mode: subagent`, `"deny"`, porque un `ask` a profundidad de delegación dos o mayor se cuelga (#39112) y el prompt ya le dice a un sub-agente que pare e informe. El runtime pasa `path.relative(worktree, archivo)` como patrón, así que cada entrada tiene además una forma `*/`, que también atrapa rutas fuera del proyecto.
   - **Por qué el piso incluye `*.env` y `*.env.*`.** Antes, el `"read": "allow"` plano de Pegasus pisaba en silencio el default del propio runtime, que pregunta por `*.env` y `*.env.*`. El piso cubre `.env`, `.env.*`, `*.env` y `*.env.*`, de modo que Pegasus nunca es más débil que ese default; como él, también atrapa nombres como `app.env.ts`. Cubre además `.ssh/`, `.credentials/`, `secrets/`, `.aws/credentials`, `.config/gh/hosts.yml`, `*.pem` y `*.key`.
   - **Sin excepción para `.env.example`, `.env.sample` ni `.env.template`.** La regla de la persona lista `.env.*` sin excepciones. El costo: un sub-agente no puede leer una plantilla de entorno, y un primario pregunta.
   - **Claude Code.** `permissions.ask` lleva reglas `Read` y `Edit` sobre las formas `//**/` de las entradas de archivo. Las entradas de directorio ya estaban en `permissions.deny`, y `deny` gana a `ask`. Los permisos allí son por sesión, así que los sub-agentes también reciben la pregunta; en una sesión sin cabeza, un `ask` actúa como rechazo. La documentación enuncia la cobertura de Bash (`cat`, `sed`, redirecciones) sólo para reglas `deny`, así que el piso no la reclama para `ask`.
   - **La guardia de push de los sub-agentes crece.** En OpenCode: un prefijo de entorno (`FOO=1 git push`) y una ruta absoluta al binario. En Claude Code: una ruta absoluta al binario (sus reglas ya coincidían pasado un prefijo de entorno). En las dos: los `gh` que escriben hacia afuera, `pr create`, `pr merge`, `issue create`, `release create` y `repo create`. La forma con prefijo de entorno de OpenCode coincide con cualquier `=` antes del texto del comando; sólo dispara si más adelante en la línea aparece ` git push` o ` gh <escritor>`. Es un sobre-aviso conocido y aceptado.
   - **Sigue sin cubrirse:** `bash` de OpenCode sobre archivos sensibles (`cat .env`); `grep` y `glob`, cuyo patrón es de búsqueda y no una ruta; los symlinks; los alias y `sh -c`; las banderas globales de `gh` antes del subcomando (`gh -R x pr create`); `gh api -X POST` y `gh pr comment`; y `git * push *` sigue preguntando de más por cosas como `git log --grep push x`.
   - Es un piso contra el descuido, no una frontera contra un agente que busca evitarlo.

3. **OpenCode 2 en espera (decisión del 2 de octubre de 2026).** La persona decidió esperar. La evidencia, al 2026-10-02: `opencode-ai` latest es 1.18.34 y las releases «Latest» de GitHub son todas 1.18.x; v2 sale aparte como `@opencode/cli`, en 2.0.22, con 22 versiones en tres semanas desde el 11 de septiembre y sin notas de release publicadas (#52184); el issue del propio equipo «V2 beta: isolate storage/database from stable OpenCode data» (#34831) está abierto, todos los canales resuelven a `opencode.db` y v2 le aplica sus migraciones; hubo regresiones entre parches (#52259, #52284); su binario también se llama `opencode`, así que tapa al 1.x en el PATH; no hay fecha anunciada. Se retoma cuando `opencode-ai` latest pase a 2.x o la release «Latest» de GitHub sea v2, cuando se cierre #34831, o cuando aparezcan notas de release. El relevamiento anterior de lo que v2 rompe sigue valiendo como mapa, pero hay que volver a verificarlo entonces.

4. **La entrega en paralelo, medida en sus caminos de fallo.** La entrega en paralelo se midió en vivo también en sus caminos de fallo, con Claude Code como coordinador. Ante un conflicto de cherry-pick el coordinador aborta, no resuelve a ciegas, deja intactos los worktrees, las ramas y el directorio de la corrida, y deja `main` limpio; en una corrida interrumpida quedan los worktrees, las ramas `<run-id>/<unidad>` y el directorio de la corrida sin ningún commit, y una nueva sesión los encuentra con `git worktree list`, los inspecciona y pregunta antes de descartar cambios sin commitear en lugar de borrarlos. Dos límites quedaron a la vista: los escritores pueden ejecutar los tests con una ruta relativa contra el checkout principal, porque la herramienta Bash no tiene parámetro de directorio de trabajo, y el control de aislamiento no puede detectarlo si los archivos ignorados ya existían en la base; además, el informe de un conflicto debe nombrar la ruta de cada worktree y de la corrida, cosa que el coordinador omitió en la medición. El camino de una unidad lanzada que falla no se llegó a observar, porque el coordinador retiró en la triage la unidad contradictoria antes de lanzarla.

   Los arreglos del procedimiento llegan en paralelo: un conflicto ahora dice si la partición estaba mal o si `main` se movió, y nombra cada ruta restante; el brief lleva el comando de pruebas con rutas absolutas; el `rm` espera sólo a las unidades LANZADAS; hay un paso corto de recuperación para una corrida interrumpida; y la regla de comandos también prohíbe `$VAR` y `cd`.

5. **Deudas.** Se cierra la del piso de permisos. La de la guardia de push queda con lo que falta (lista arriba). OpenCode 2 queda «en espera», con sus criterios de reanudación. La de la entrega en paralelo se actualiza: los caminos de conflicto y de corrida abortada están medidos; una unidad lanzada que falla sigue sin observarse; los riesgos de rutas relativas de OpenCode y el modo fork de Claude Code siguen sin medirse; y el largo del procedimiento sigue preocupando.

Medido en vivo con Claude Code (8c82c18): los escritores ejecutan el comando de tests con rutas absolutas dentro de su propio worktree y ningún comando del coordinador ni de los escritores usa `cd` ni expansiones; ante una base que se movió, el coordinador lo distingue de un error de partición y deja `main` limpio con todos los worktrees en su lugar. Quedaban dos huecos, ya corregidos: el deber de listar rutas sólo se disparaba después de un conflicto de cherry-pick (ahora toda detención de la integración, antes o después de un pick, lista la ruta de cada worktree restante y de `<root>/<run-id>`), y el brief del revisor no llevaba las reglas de comandos y de rechazos (ahora las lleva, y sus pruebas corren como comandos sueltos con rutas absolutas).

## 7.6.1: los archivos sensibles se abren con la herramienta de archivos, y engram sale del fork propio

Registra dos decisiones y lo que queda pendiente.

1. **El piso no alcanza al shell, y el agente prefiere el shell.** Una prueba en vivo del 3 de octubre de 2026, en Claude Code 2.1.288 y en modo auto, mostró lo que significa en la práctica. La persona dio permiso explícito para archivos falsos concretos; el orquestador nunca usó Read ni Edit: las cuatro veces usó el shell (`cat ~/prueba/.env`, `cat` sobre otros dos archivos y `echo 'OTRA=2' >> ~/prueba/.env`), así que la confirmación nunca apareció. La interfaz mostró un `cat` del shell como «Read 1 file», de modo que a la persona le parece una lectura con herramienta. Cuando la persona pidió expresamente «la herramienta Read», la confirmación sí apareció, también en auto. Se midió además, interactivo y sin cabeza, en dos usuarios de prueba: la pregunta de la herramienta de archivos se cumple en los modos auto, por defecto y bypass.

2. **Qué cubre cada mecanismo.** El `ask` del piso cubre las herramientas de archivos (leer y editar) en las dos CLIs; no cubre comandos de shell como `cat .env` o `echo X >> .env`. Sólo una regla `deny` llega al shell, y sólo en Claude Code.

3. **La decisión: una frase en la regla.** `## Sensitive Files` dice ahora que, cuando la persona da el permiso, el agente abre el archivo con su herramienta de lectura o edición de archivos y nunca con un comando de shell, porque la confirmación de estos archivos cubre esas herramientas y no el shell. Así se aplica la confirmación propia de la CLI. Es una guía para el modelo, no un cumplimiento: un agente que la ignore sigue pudiendo usar el shell. Se descartó un `ask` sobre el contenido del comando con nombres como `.env`, porque también preguntaría por comandos inocentes, por ejemplo cualquiera que contenga `process.env`. La frase es neutra respecto de la CLI y está fijada en `tests/test_sensitive_files_rule.py`. Medido sin cabeza en Claude Code, con seis pedidos de leer o editar un archivo sensible y el permiso dado en el chat: antes de la frase, con Sonnet, dos de seis fueron por el shell (las dos ediciones, con `>>`), y ejecutaron sin confirmación; con la frase, cero de doce, con Sonnet y con Opus: todas fueron por la herramienta de archivos, la regla las frenó y ninguna intentó rodearla con `cat` o `echo`.

4. **engram se toma del fork propio, en 1.20.0.** La persona decidió que Pegasus se queda en engram 1.20.0 y no sube a versiones más nuevas, porque no le gusta la dirección que está tomando engram (existe engram 3.0.0). Upstream, la línea 1.20 está congelada: la v1.20.0 salió el 20 de julio de 2026, no hubo ningún 1.20.x posterior ni rama de mantenimiento, todo el desarrollo siguió hacia 2.x y 3.x, y su política de seguridad dice que sólo la última versión estable recibe arreglos. Por eso existe el fork `balerdis/engram` (licencia MIT): su rama por defecto (entonces `v1.20`, hoy `main`) y el tag `v1.20.0` están en el commit de la 1.20.0 original, y su release `v1.20.0` publica los mismos binarios byte a byte, verificados contra el `checksums.txt` de upstream. `content/mcp/engram.md` apunta ahora a esa release; el checksum no cambia, porque es el mismo archivo. Para quien instala no cambia nada; Pegasus sólo deja de depender de que upstream mantenga esos archivos publicados. Una instalación que vinculó un engram propio no lo baja: sigue con su binario. La base, `~/.engram/engram.db`, no depende del binario que la abra. Lo pendiente queda en la tabla de deudas.

5. **La deuda del piso de permisos** queda anotada como atendida por guía, no por cumplimiento.

## 7.6.2: engram 1.20.1, el primer build propio del fork

1. **Pegasus baja engram 1.20.1 desde el fork.** `content/mcp/engram.md` apunta a la release `v1.20.1` de `balerdis/engram`, con su checksum. Es la primera versión que arma el propio fork, y no trae funciones nuevas:
   - El aviso de actualización mira las releases del fork en vez de las del original, y dice `pegasus update` (o `darq update`). `ENGRAM_NO_UPDATE_CHECK=1` lo apaga. Nunca sale en `engram mcp` ni en `engram serve`, que son los modos que usan OpenCode y Claude Code.
   - `engram setup claude-code` instala el plugin del fork.
   - El fork ya no publica en Homebrew.
2. **La base no cambia.** La 1.20.1 abre la misma `~/.engram/engram.db` que la 1.20.0, y las dos pueden usarla a la vez. Una instalación que vinculó un engram propio (`--mcp engram=<binario>`) sigue con su binario.
3. **Lo del fork vive en el fork.** Sus decisiones, la regla de que sus migraciones solo agregan y sus ideas están en `docs/arquitectura-engram.md` de `balerdis/engram`. Acá queda solo qué versión baja Pegasus y desde dónde. Cada release del fork va acompañada de una release de Pegasus y de DARQ que sube `content/mcp/engram.md`.

## 7.7.0: Claude Code registra sesiones y prompts en engram con hooks propios, update limpia versiones viejas, y una herramienta para las dependencias

Registra tres cambios, lo que se midió y lo que queda pendiente.

1. **Claude Code registra sesiones y prompts en engram con hooks propios.** Sólo cuando el servidor engram está elegido, Pegasus agrega tres entradas a `~/.claude/settings.json`, como `append` con huella (`uninstall` y `restore` sacan exactamente esas tres y los hooks del usuario no se tocan), y escribe `<data_dir>/hooks/engram-hook.py`, un script de biblioteca estándar. `SessionStart` (`startup|resume|clear|fork`, síncrono) arranca `engram serve` con el binario que administra Pegasus si no contesta (con un engram vinculado usa el `engram` del PATH) y registra la sesión. `UserPromptSubmit` (asíncrono) registra el prompt con los filtros del plugin de OpenCode: más de 10 caracteres, etiquetas privadas fuera, credenciales tapadas con el mismo catálogo y recorte a 2000. `SubagentStop` (asíncrono) manda `last_assistant_message`, si pasa de 50 caracteres, a la captura pasiva con `source: subagent-stop`; engram no guarda nada sin una sección `## Key Learnings` (el opt-in de 7.2.0), así que no vuelve el aluvión de 7.1.0.

2. **Garantías, y lo que quedó afuera a propósito.** La salida estándar siempre queda vacía (el hook nunca le agrega texto al modelo), siempre termina en `0` y no hace nada dentro de un sub-agente (`agent_id`). El comando va envuelto como `command -v python3 ... && python3 ... || true`, así que sin `python3` no hay error. Respeta `ENGRAM_PORT` (7437 por defecto) y `ENGRAM_HTTP_TOKEN`. No hay `Stop` ni `SessionEnd`, ni recordatorios periódicos, ni protocolo de memoria inyectado: todo eso contradice la decisión de 7.1.0 de que escribe en memoria sólo quien habla con la persona, y sólo cuando pasó algo durable. La recuperación después de compactar es el slice siguiente.

3. **Por qué no se instala el plugin de Claude Code del fork de engram.** Registraría un segundo servidor MCP con otros nombres de tool, salteando las reglas por herramienta y la versión fijada de Pegasus; depende del PATH, de `jq` y de `curl`; queda fuera del journal, así que `uninstall` y `restore` no lo revertirían; no se podría renombrar para DARQ; e inyecta el protocolo «guardá AHORA» y un recordatorio de 15 minutos, que es el aluvión de 7.1.0. Además trae defectos: su script de `SubagentStop` lee un campo `.stdout` que Claude Code nunca manda, así que su captura pasiva nunca funcionó; su script de `Stop` cierra la sesión después de cada respuesta; y las sesiones retomadas no se registran. Esos defectos se arreglan en engram 1.21.0 del fork; a Pegasus no le afectan porque no lo instala.

4. **Medido en vivo** el 3 de octubre de 2026, con un build de desarrollo, en el usuario de prueba `pegasus-claude`: sesiones, observaciones y prompts pasaron de 0/0/0 a 3/1/3; el proyecto se detectó desde git; un `GITHUB_TOKEN=ghp_...` falso en un prompt se guardó como `GITHUB_TOKEN=$PEGASUS_SECRET_GITHUB_TOKEN`; y un brief de sub-agente que pedía `## Key Learnings` produjo una observación pasiva.

5. **Lo que encontró la revisión adversarial, ya arreglado** (y aplicado también a los plugins de OpenCode):
   - Se recortaba antes de tapar: un secreto que cruzaba el carácter 2000 filtraba su prefijo. También pasaba en `engram.ts`. Ahora se tapa y después se recorta.
   - Las llamadas locales a engram ignoran el proxy HTTP del entorno (`ProxyHandler({})` en Python, `proxy: false` en Bun), porque el prompt y el token Bearer podían ir a un proxy corporativo.
   - Por encima del tope de detección de 256 KiB, falla cerrado: un prompt se corta al tope antes de tapar, y un mensaje de sub-agente demasiado grande no se manda.
   - El borrado de `<private>` es lineal: una expresión cuadrática tardaba más de 60 s con unos 250 KB de etiquetas sin cerrar. También en `secret-transport.ts`.
   - Un `append` JSON-pointer `/.../-` se niega cuando el destino es un objeto, en vez de escribir una clave `"-"`: protege un `settings.json` de forma rara del usuario.

6. **Hallazgo: el puerto de engram es compartido por todos los usuarios de la máquina.** Si el `engram serve` de un usuario ocupa `127.0.0.1:7437`, los hooks de otro usuario (y el plugin de engram de OpenCode, que ya se comportaba así) mandan sus sesiones y prompts a la base del primero. La prueba en vivo usó `ENGRAM_PORT=7438` para evitarlo. Es una deuda nueva (ver la tabla).

7. **Lo que sigue siendo imposible bajo Claude Code.** El transporte de credenciales: `UserPromptSubmit` no puede reescribir el prompt, así que el modelo sigue viendo lo que se escribe. Sólo la copia guardada en engram está cubierta. Brecha chica conocida: el hook no tiene el equivalente de `redactKnownValues` del plugin.

8. **`update` borra las versiones viejas de los servidores MCP que nadie usa.** Después de un install o update exitoso (journal guardado), borra los directorios `<data_dir>/mcp/<nombre>/<versión>` fuera del conjunto a conservar; `uninstall` también poda, y deja sólo los destinos de las instalaciones que quedan. El conjunto a conservar es: todo destino registrado por cualquier instalación del journal (la carpeta la comparten las instalaciones de OpenCode y de Claude Code), las versiones fijadas hoy, y el destino que usaba esta CLI antes del update, para que un `pegasus restore` siga andando (ese se borra en el update siguiente). Sólo se tocan hijos directos `<nombre>/<versión>` de nombres que Pegasus administra, nunca se sigue un symlink, y un `<nombre>` vacío se borra. El borrado es de mejor esfuerzo: una falla nunca hace fallar el comando y se informa. El reporte es `pruned_dependencies` (`removed`, `failed`) y `--dry-run` lista lo que se borraría. **Consecuencia documentada:** restaurar una generación más vieja que un update atrás pide un `pegasus update` después, porque ese binario ya no está y `restore` nunca descarga.

9. **`toolCounts` salió de `engram.ts`.** Código muerto: se escribía y nunca se leía (la nota de 7.2.0 lo había dejado a propósito).

10. **`tools/check_dependency_updates.py`.** Herramienta de quien mantiene, para correr antes de cada release (ya está en `docs/release-distribution.md`). Lista las versiones más nuevas de cada dependencia fijada en `content/mcp/*.md`: releases de GitHub para cbm y engram, npm para playwright. No cruza la versión mayor, y toda 0.x más nueva se marca para revisión manual. Por defecto sólo informa; `--strict` sale con `1`. Es idéntica byte por byte en DARQ porque descubre `src/*/content/mcp`. **Primera corrida real:** playwright 0.0.83 está disponible (fijado en 0.0.79); cbm y engram están al día. Ver la deuda en la tabla.
