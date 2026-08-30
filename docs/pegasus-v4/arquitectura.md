# Pegasus Harness v4: núcleo agnóstico y adapters por CLI

Pegasus v4 separa **qué distribuye** (contenido común a cualquier CLI de agentes) de **cómo lo materializa** (un adapter por CLI). El motor deja de conocer nombres de CLIs: recibe contenido del núcleo, se lo da al adapter, y el adapter decide dónde va y con qué forma. Es un rediseño con ruptura de compatibilidad respecto de v3.1.x.

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
| Lenguaje y dependencias | Python 3.12+, dependencias permitidas con versiones y hashes fijos. |
| Punto de entrada | `~/.local/bin/pegasus` + venv privado. |

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
| `skills/` | 27 | Nada |
| `commands/` | 16 | Nada |
| `agents/` | 12 | Nada |
| `system-prompt/` | 1 | Nada |
| `mcp/` | 0 | Sigue viviendo en `manifests/release-contract.json` |
| `policies/` | 0 | Sin extraer |

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

En OpenCode son once: cinco plugins escritos contra su API de plugins, el `package.json` y el lockfile de los que esos plugins dependen, la herramienta que uno de ellos invoca con su launcher, su plantilla de entorno, y un archivo de datos del propio adapter.

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

El criterio no es "reglas arriba, estilo abajo": es a quién obliga cada cosa. La mayoría de las reglas de trabajo — no agregar atribución de herramientas a un commit, verificar antes de afirmar — tienen que obligar a cualquier agente, no solo al que casualmente cargaba ese archivo como prompt. Pero una regla sobre cómo trabaja una voz en particular es de esa voz: `Never build after changes` vive en `king-pegasus.md` a propósito, porque la skill `sdd-verify` exige correr el build y registrar su hash, y una prohibición global de compilar contradiría a algo que embarcamos.

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

La TUI se dibuja con `curses`, de la biblioteca estándar. No agrega ninguna dependencia, y por lo tanto no agrega nada que la unidad 4 tenga que fijar con hash ni meter en el venv privado. Las pantallas que siguen son listas verticales con un cursor y teclas de una letra: no piden color, ni layout anidado, ni nada que justifique traer un paquete —y menos uno que arrastre un segundo— para dibujarlas.


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

Cuatro pasos, con opción de volver en cada uno.

```
CLI → agente → proveedor → modelo → [esfuerzo]
```

```
Models · OpenCode

  Agent                    Current model
  ▸ pegasus-orchestrator   (no model)
    sdd-apply              anthropic/claude-sonnet-5 · high
    sdd-verify             (no model)
    …

  enter: configure · d: remove current model · esc: back
```

`d` devuelve el agente a "sin modelo": borra la preferencia de su propio store y se renderiza el default. No toca el journal, porque la asignación de modelo nunca vivió ahí.

### Paridad con flags

La TUI no puede hacer nada que los flags no puedan. Esta regla protege `INSTALL_BY_AGENT.md`, que es el diferencial de Pegasus: instalación conducida por un agente.

```bash
pegasus                                          # TUI
pegasus install --cli opencode --mcp context7 --mcp engram
pegasus models set --cli opencode --agent sdd-apply --model anthropic/claude-sonnet-5 --effort high
pegasus models unset --cli opencode --agent sdd-apply
pegasus uninstall --cli opencode
pegasus doctor --json
```

Un test de contrato verifica que cada acción de la TUI tenga su comando equivalente.

#### Qué existe hoy

`install`, `uninstall`, `doctor`, `restore` y `setup`, con `--json` en los primeros cuatro y `--dry-run` en install. `install` acepta `--mcp ID` (repetible): un servidor no nombrado no se instala. `models set` y `models unset` asignan y quitan el modelo de un agente. Cada reporte declara su esquema `pegasus/cli-report/v1`.

Tres cosas que la CLI hace y conviene no perder:

- **Pregunta antes de hacer.** El journal se consulta con `ensure_writable()` **antes** del primer artefacto. Una negativa descubierta al final llegaría con los artefactos ya en disco y sin registro: una instalación que existe y no se puede desinstalar, el peor resultado que este motor puede producir. Preguntar primero lo convierte en un mensaje y un home intacto.
- **El preflight pregunta las dos cosas: si se puede escribir y si se puede leer lo que ya hay.** Un journal que no se puede leer es uno que no se puede extender, y descubrirlo después de colocar los artefactos los dejaría en disco sin nada que los registre — con `doctor` fallando contra ese mismo journal ilegible, así que no quedaría forma de enterarse de que están.
- **`ensure_writable()` es un preflight, no una garantía.** Rechaza root y homes ajenos, que son las causas previsibles. No puede prometer que el guardado posterior funcione: el disco se puede llenar, los permisos pueden cambiar entre medio, puede haber cuota. Por eso el camino de falla al registrar tiene que ser correcto igual, y no solo improbable.
- **Si igual no se puede registrar, se retira lo instalado.** Y se informa lo que no pudo volver atrás: Pegasus posee claves dentro de un archivo de configuración, nunca el archivo, así que uno que tuvo que crear sobrevive vacío. Inofensivo, pero afirmar un deshecho limpio sería una mentira chica en el único reporte que alguien lee cuando algo ya salió mal.
- **El rollback deshace esta corrida, nunca lo que corridas anteriores ya poseían.** Hay dos vistas de la misma instalación y confundirlas sale caro: la **acumulada** es la que se registra —todo lo que ese CLI posee, viejo y nuevo— y la **colocada** es solo lo que esta corrida escribió. Solo la segunda puede tocarse al deshacer. Una reinstalación no crea nada, así que no hay nada que deshacer; retirar la vista acumulada borraría una instalación que funciona mientras el journal —que no se llegó a escribir, porque escribirlo es lo que falló— sigue afirmando que está entera. Es la misma mentira que los artefactos huérfanos, apuntando para el otro lado.
- **Reinstalar no reduce lo que el journal ya poseía.** La segunda corrida no crea nada, porque todo lo que quiere ya está: su propio trabajo de la primera. Reemplazar el registro con ese resultado vacío dejaría los 84 artefactos huérfanos para siempre, sin nada que pruebe que fueron nuestros. Las entradas previas se conservan y las nuevas se suman.

#### Actualizar todavía no está definido

En 4.0.0 no hay comando de actualización, y las dos preguntas que traería no tienen respuesta escrita todavía:

- Si un release futuro **deja de embarcar** un artefacto que el anterior instaló, su entrada sigue en el journal y nadie la retira. Queda poseído para siempre hasta que se desinstale entero.
- Si un artefacto **cambia de contenido** bajo el mismo id, reinstalar no lo actualiza: el planner ve que la ruta existe, lo trata como colisión y lo saltea, y la huella del journal nunca se refresca.

Las dos son consecuencias coherentes de una instalación aditiva sin actualización, no defectos. Pero cuando se diseñe `update` hay que decidirlas explícitamente, porque el journal es lo único que sabe qué había antes.

#### Una inconsistencia conocida

`detect()` es la única operación de disco que **no pasa por el puerto `FileSystem`**: el adapter resuelve con `shutil.which` contra el PATH y un `is_dir()` real. Eso hace que la detección mire la máquina donde corre, sin importar lo que se le diga al puerto, y que no se pueda probar sin tocar el disco de verdad. Arreglarlo cambia la firma de `CliAdapter.detect` y el puerto necesitaría saber buscar en el PATH, así que es una unidad de trabajo aparte.

---

## Estructura del repositorio

```
pegasus-harness/
├── bin/pegasus                    # shim de arranque
├── pyproject.toml
├── requirements.txt               # versiones y hashes fijos
├── src/pegasus/
│   ├── __main__.py
│   ├── cli.py                     # flags, modo desatendido
│   ├── core/
│   │   ├── content.py             # carga y valida el núcleo de contenido
│   │   ├── types.py               # descriptores, Artifact, Layout, Detection
│   │   ├── registry.py            # registro de adapters, falla cerrado
│   │   ├── planner.py             # plan, apply, rollback
│   │   ├── journal.py             # journal v4
│   │   └── ownership.py           # huellas, colisiones, mutaciones
│   ├── ports/
│   │   ├── cli_adapter.py
│   │   ├── filesystem.py
│   │   ├── journal_store.py
│   │   └── dependencies.py
│   ├── adapters/
│   │   ├── opencode/
│   │   │   ├── adapter.py
│   │   │   ├── layout.py
│   │   │   ├── render.py
│   │   │   ├── models.py          # proveedores y modelos
│   │   │   └── manifest.py
│   │   └── _template/             # esqueleto para un CLI nuevo
│   ├── infra/
│   │   ├── fs_posix.py
│   │   ├── fs_windows.py
│   │   ├── journal_store_file.py  # el journal como archivo, sobre el puerto FileSystem
│   │   └── deps_fetcher.py
│   ├── tui/
│   │   ├── app.py
│   │   ├── install.py
│   │   └── models.py
│   └── content/                   # ← el núcleo, agnóstico
│       ├── skills/
│       ├── agents/
│       ├── prompts/
│       ├── commands/
│       ├── mcp/
│       └── policies/
├── manifests/                     # generados, verificados en CI
├── tools/build_catalog.py
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
| Descriptor de contenido | `pegasus/content-descriptor/v1` | Forma de skills, agentes, comandos, prompts, MCPs, políticas |
| Catálogo de artefactos | `pegasus/artifact-catalog/v4` | Salida generada del render, con huellas |
| Journal de ownership | `pegasus/journal/v4` | Estado de instalación |
| Asignación de modelo | `pegasus/model-assignment/v1` | Proveedor, modelo y esfuerzo por agente |
| Reporte de la CLI | `pegasus/cli-report/v1` | Salida JSON de `install`, `uninstall` y `doctor` |

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
| 4 | Launcher, venv privado, empaquetado | `pegasus` disponible en el PATH tras instalar: el shim `bin/pegasus`, `pegasus setup` para levantar el venv desde un checkout, y `tools/build_release_evidence.py` atando wheel, lockfile y shim al commit que los produjo. `INSTALL.md` documenta el recorrido de punta a punta y deja constancia de qué se corrió en esta verificación y qué no —el único paso no ejecutado es el `pip install` con red real, prohibida en este entorno | Entregada |
| 5 | TUI: menú principal e instalación | Instalación completa sin escribir un flag: menú de cinco entradas (`Install`, `Configure models`, `Status and diagnostics`, `Uninstall`, `Exit`), instalación con vista previa (`InstallPlanScreen`, el mismo reporte de `install --dry-run`) separada del punto sin retorno | Entregada |
| 6 | TUI: configuración de modelos | Asignar y quitar modelo por agente, con la preferencia guardada en el estado propio de Pegasus: la caminata de cuatro pasos (`ModelsScreen`) llama a `cli.models_set`/`cli.models_unset`, que escriben en el store real de asignaciones | Entregada |
| 7 | Actualización de una instalación existente | Reinstalar sobre una instalación propia actualiza el payload. La segunda mitad de lo entregado —preservar y reportar lo que el usuario reescribió— la reemplazó la unidad 9 | Entregada |
| 8a1 | Categoría `mcp/`, descriptor y render del servidor | Un MCP remoto se instala de verdad, con su convención embarcada y su permiso concedido | Entregada |
| 8a2 | Selección del usuario y reversibilidad | `--mcp` decide qué servidores se instalan, y dejar de nombrar uno lo retira. El retiro salió genérico: alcanza a cualquier artefacto que el journal reclame y el render ya no produzca | Entregada |
| 8b1 | El directorio propio de Pegasus y su resolutor | El journal, los snapshots y lo que venga cuelgan de un único lugar que la plataforma decide (`FileSystem.data_dir`), y la unidad 4 lo adopta: `bin/pegasus` y `journal_store_file.py` resuelven el mismo directorio, `bootstrap.venv_dir` cuelga el venv de ahí | Entregada |
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

Se separan. `requires_tools` y `optional_tools` nombran **sólo herramientas nativas**; `optional_mcp` nombra **ids de servidor**. Y no hay `requires_mcp`: un servidor que el usuario puede declinar no puede ser un requisito, y ahora eso es estructural en vez de una regla sostenida por un test — no hay campo donde escribirlo.

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

La retención guarda 5 generaciones, y no es un argumento de disco: el contenido son 80 archivos y 356 KB, el catálogo renderiza 90 archivos y 18 claves de configuración, así que un snapshot de reinstalación son unos 400 KB y cinco generaciones son unos 2 MB. Lo que la retención decide en realidad es cuánto atrás llega la promesa de recuperación.

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

**`mode_of` va para el otro lado, y su default merece una aclaración que costó caro.** En `core/planner.py`, dentro de `_put_back`:

```python
filesystem.write_atomic(path, content, mode=mode if mode is not None else 0o644)
```

El `None` que llega de `mode_of` puede significar "la ruta no existe" o "no pude leer sus bits", y las dos colapsan en `0o644`. Leído así parece una pérdida de confidencialidad: un archivo del usuario en `0600` que el rollback deja legible por todos.

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
2. **Unidad 4.** Launcher, venv privado, empaquetado. Destraba la TUI.
3. **Unidades 5 y 6.** La TUI.

Ya entregado, en este orden: el cierre de la unidad 3 —el `.env` real del skill registry y el retiro de los marcadores sin lector—; la unidad 7, que fue temprano por ser la herramienta con la que se verifica todo lo que viene después; la **8a1**, con la categoría `mcp/` y el primer servidor instalado de verdad; la **unidad 9**, en cadena de cuatro PRs; la **8a2**, que cerró la cadena 8a con la selección del usuario y un retiro que salió genérico; y la **unidad 10**, el contrato del puerto de filesystem.

El presupuesto de revisión es de **800 líneas cambiadas por PR**. Cada unidad se mide al planificar sus tareas; la que se pase se parte en una cadena, con la estrategia definida antes de empezar a escribir código. La unidad 1 ya se midió y por eso está partida en 1a y 1b.

---

## Deudas sin unidad asignada

Trabajo conocido que no pertenece a ninguna unidad del corte. Se acarrea a propósito, y cada ítem declara qué lo destraba, para que el acarreo sea una decisión y no un olvido.

| Deuda | Qué la destraba |
|-------|-----------------|
| `pegasus setup` puede reconstruir el venv de una instalación **sólo si alguna vez corrió desde un checkout**: esa corrida deja sus insumos en `setup-sources/`, al lado del venv. Quien instaló siguiendo `INSTALL.md` —pip a mano, sin checkout— nunca pasa por ahí, así que para esa persona sigue negándose. El mensaje nombra los dos lugares donde buscó | Que los insumos viajen adentro del wheel, o que el recorrido documentado los deje al lado del venv. Lo primero exige duplicar `requirements.txt` y el shim dentro del paquete o un paso de build que los copie; lo segundo, dos líneas más en la guía |
| Un `refresh failed` del plugin del skill registry queda sólo en `console.error`, así que una falla del registry no se superficializa | Nada. Es del plugin, no del contrato que lo alimenta |
| Los sitios de `content.py` que lanzan `ContentError` no tienen un test de tabla que recorra todos y afirme que cada uno nombra una ruta real | Nada. Unidad candidata en cualquier momento |
| La voz `king-pegasus` explica y no puede aplicar nada de lo que explica: declara sólo `read` y su cuerpo le prohíbe generar cualquier artefacto | Nada. Es una decisión de producto sobre qué hace esa voz, y hasta tomarla no se le concede ningún servidor |
| El orquestador tiene prohibición absoluta de ejecutar —"never by running the phase work yourself"— sin umbral, y no tiene `write` ni `edit`. Prosa y herramientas están de acuerdo, así que no es un bug: es un diseño que hay que cambiar en las dos mitades a la vez | Nada. Cambiar sólo la prosa le nombraría una capacidad que no tiene |
| `restore` no puede devolver un árbol de dependencias. El snapshot excluye esos destinos porque `capture_paths` lee bytes y un árbol es un directorio, así que un install que materializó una dependencia y falló no la deshace | La 8b, cuando el snapshot sepa capturar un directorio. Hasta entonces `restore` devuelve todo lo demás exacto y esto no |
| El digest de un árbol de dependencias es la identidad de lo que se materializó, no un hash de lo que quedó en disco, así que `doctor` no puede detectar un árbol corrompido ni manipulado | Nada. Es la consecuencia elegida a conciencia, y necesitaría una verificación distinta de este campo |
| `mode_of` sigue colapsando "la ruta no existe" y "no pude leer sus bits" en el mismo `None`. Los tres llamadores del planner corren justo después de una lectura que ya tuvo éxito, así que hoy es inalcanzable | Nada. Fragilidad latente, no reproducida |
| No hay CI en el repositorio: `.github/` no existe. La estructura documentada describe `manifests/` como "generados, verificados en CI", y esa verificación no la corre nada | Nada. Es una decisión sobre si el proyecto quiere una. El procedimiento de release es manual, está escrito en `docs/release-distribution.md`, y se ejecutó tal cual para 4.0.0, 4.1.0 y 4.1.1 |
| Ningún test arranca un servidor MCP. La suite verifica que el archivo se baje, que el hash coincida, que se extraiga, que el journal lo reclame y que la configuración quede escrita — todo cierto mientras el servidor no levanta. Es lo que dejó pasar que `engram` se instalara y no funcionara en 4.0.0 y 4.1.0, y lo encontró una instalación real y no la suite | Aceptar que un test hable el protocolo contra cada servidor embarcado, lo que exige red o binarios locales y rompe la hermeticidad que el resto de la suite sostiene. Es una decisión, no un pendiente obvio |

---

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

**Lo que sigue.** La migración de tests que la unidad 10 dejó a medio camino: `tests/test_dependencies.py` y `tests/test_model_assignment_store.py` siguen enteros sobre el doble en memoria, sin la contraparte contra disco real que sus vecinos ya tienen. Y el resto vive en "Deudas sin unidad asignada", acarreado a propósito.
