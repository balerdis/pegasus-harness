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
hidden: true
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
| `agents/` | 2 | Faltan los 10 de la línea SDD y `king-gentleman` |
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

    # --- Cómo: render de cada categoría ---
    def render_skill(self, skill: Skill) -> list[Artifact]: ...
    def render_agent(self, agent: AgentDescriptor) -> list[Artifact]: ...
    def render_command(self, command: CommandDescriptor) -> list[Artifact]: ...
    def render_prompt(self, prompt: PromptDescriptor) -> list[Artifact]: ...
    def render_mcp(self, server: McpServer, resolved: ResolvedDependency) -> list[Artifact]: ...
    def render_policy(self, policy: PolicyDescriptor) -> list[Artifact]: ...

    # --- Lo que el adapter aporta por su cuenta ---
    def own_artifacts(self, env: Environment) -> list[Artifact]: ...

    # --- Modelos: solo si capabilities().per_agent_model es True ---
    def model_catalog(self, env: Environment) -> ModelCatalog: ...
    def read_model_assignments(self, env: Environment) -> dict[str, ModelAssignment]: ...
    def render_model_assignment(
        self, agent_id: str, assignment: ModelAssignment | None
    ) -> Artifact: ...
```

`render_model_assignment` con `assignment=None` produce el artefacto que **quita** el modelo. Ese es el camino de vuelta a "sin modelo elegido".

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
| Revertir | Borrar el archivo, o restaurar `before` | `unset_at(doc, pointer)`, o restaurar `before` |

`set_at` y `unset_at` son dos funciones genéricas que navegan un árbol de diccionarios y listas creando lo que falte. No mencionan ningún CLI.

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
| `DependencyFetcher` | Descargar, verificar y probar MCPs | Aísla la red; ya existe en v3, se mantiene el contrato |
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
- [ ] Cada capacidad en `True` tiene su ancla de `Layout` no nula
- [ ] Cada capacidad en `True` tiene su método `render_*` implementado
- [ ] Cada capacidad en `False` no expone ruta ni render (evita capacidades fantasma)
- [ ] `per_agent_model` en `True` implica los tres métodos de modelos
- [ ] No hay dos adapters con el mismo `id`

Este es el mecanismo que evita que la abstracción se degrade cuando se agregue el cuarto o quinto CLI.

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
| Solo `baseline_digest` (huella posterior) | `before` + `after_digest` | Permite **restaurar**, no solo borrar o preservar |
| Una instalación global | Instalaciones por CLI | Se puede tener Pegasus en dos CLIs con ciclos de vida independientes |
| Clave plana (`key`) | JSON Pointer | El motor escribe rutas anidadas sin conocer el esquema |
| Sin registro de mutaciones | `mutations[]` con rebase de huella | Configurar un modelo no rompe el ownership |

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
          "before": null,
          "after_digest": "sha256:5e6f…",
          "mode": "0644",
          "ownership": "owned",
          "created_at": "2026-08-14T00:41:09Z",
          "mutations": []
        },
        {
          "id": "agent:sdd-apply",
          "kind": "config-key",
          "target": "/home/serg/.config/opencode/opencode.json",
          "pointer": "/agent/sdd-apply",
          "before": null,
          "after_digest": "sha256:7a8b…",
          "ownership": "owned",
          "adopted": false,
          "created_at": "2026-08-14T00:41:09Z",
          "mutations": [
            {
              "at": "2026-08-14T01:10:00Z",
              "by": "set-model",
              "after_digest": "sha256:9c0d…"
            }
          ]
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

### Semántica de `before`

| Valor | Significa | Al desinstalar |
|-------|-----------|----------------|
| `null` | No existía antes de Pegasus | Se elimina |
| valor previo | Existía, o el usuario lo editó y lo adoptamos | Se **restaura** al valor previo |

Los archivos existentes se siguen tratando como colisión y se saltean, igual que en v3. La adopción con `before` no nulo queda reservada a claves de configuración, donde el valor previo es chico y se guarda en línea.

### Semántica de `mutations[]`

Cuando el usuario configura un modelo, el flujo es:

1. Se verifica que la huella actual del artefacto coincida con `after_digest`.
2. Se aplica el cambio.
3. Se agrega una entrada a `mutations[]` y se actualiza `after_digest`.

Con eso, el artefacto sigue siendo reconocido como propio y el desinstalador lo limpia normalmente. Esto resuelve el problema que en v3 dejaría configuración huérfana para siempre.

### Cuando el usuario editó el artefacto: preguntar y adoptar

Si la huella del paso 1 no coincide, el usuario editó eso a mano. Pegasus **no rechaza el cambio ni pisa en silencio**: pregunta.

```
El agente sdd-apply fue modificado fuera de Pegasus.

  Tu versión actual:   { "model": "openai/gpt-5", "temperature": 0.2 }
  Cambio solicitado:   model → anthropic/claude-sonnet-5

  ▸ Adoptar: aplico el cambio y conservo el resto de tu configuración
    Cancelar: no toco nada
```

Al adoptar:

- Se guarda el valor actual del usuario en `before` (si `before` ya era `null`, pasa a contener esa versión).
- Se marca la entrada con `adopted: true`.
- Se aplica el cambio **preservando las claves que el usuario agregó**: se escribe solo el campo del modelo, no se reemplaza el objeto entero.
- Se registra la mutación con `by: "set-model-adopted"`.

La consecuencia importante es en la desinstalación: un artefacto con `adopted: true` **se restaura al valor previo del usuario** en lugar de eliminarse. Pegasus se retira dejando la edición del usuario intacta.

En modo desatendido no hay a quién preguntar, así que el comportamiento es explícito por flag:

```bash
pegasus models set … --on-modified ask       # default en TUI
pegasus models set … --on-modified adopt     # adopta sin preguntar
pegasus models set … --on-modified skip      # deja el artefacto como está y reporta
```

Sin flag, el modo desatendido usa `skip` y lo informa en su salida JSON. Nunca adopta por omisión: adoptar es una decisión del usuario, y en desatendido no hay usuario presente.

### Reglas invariantes

- [ ] Todo `target` está contenido dentro del home del usuario
- [ ] El journal lo escribe el usuario dueño del home, nunca root
- [ ] Escritura atómica: archivo temporal, `fsync`, `rename`
- [ ] Al desinstalar, un artefacto cuya huella no coincide se preserva y se reporta
- [ ] Un `link` nunca se borra: Pegasus no es dueño de dependencias preexistentes

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

### Agentes configurables en 4.0.0

Los 10 de la línea SDD, más los dos de coordinación:

```
sdd-init      sdd-explore    sdd-propose    sdd-spec      sdd-design
sdd-tasks     sdd-apply      sdd-verify     sdd-archive   sdd-onboard
pegasus-orchestrator         king-gentleman
```

En v3.1.2 se embarcan los 10 prompts SDD pero solo uno está cableado como agente. v4 corrige eso: cada fase existe como subagente real, con su prompt y su modelo configurable.

---

## Interfaz de usuario

### Menú principal

```
Pegasus Harness 4.0.0

  ▸ Instalar
    Configurar modelos
    Estado y diagnóstico
    Desinstalar
    Salir
```

### Instalar

Detecta CLIs soportados y presentes. Selección de a uno.

```
¿Dónde instalar Pegasus?

  ▸ OpenCode          ~/.config/opencode        soporte completo
```

Luego muestra el plan (qué se crea, qué se saltea por colisión, qué dependencias requieren confirmación) y pide confirmación por dependencia, igual que hoy.

### Configurar modelos

Cuatro pasos, con opción de volver en cada uno.

```
CLI → agente → proveedor → modelo → [esfuerzo]
```

```
Modelos · OpenCode

  Agente                  Modelo actual
  ▸ pegasus-orchestrator  (sin modelo)
    sdd-apply             anthropic/claude-sonnet-5 · high
    sdd-verify            (sin modelo)
    …

  enter: configurar · d: quitar modelo · esc: volver
```

`d` devuelve el agente a "sin modelo": escribe el artefacto que elimina la clave y registra la mutación.

### Paridad con flags

La TUI no puede hacer nada que los flags no puedan. Esta regla protege `INSTALL_BY_AGENT.md`, que es el diferencial de Pegasus: instalación conducida por un agente.

```bash
pegasus                                          # TUI
pegasus install --cli opencode --confirm cbm --decline playwright
pegasus models set --cli opencode --agent sdd-apply --model anthropic/claude-sonnet-5 --effort high
pegasus models set --cli opencode --agent sdd-apply --model … --on-modified adopt
pegasus models unset --cli opencode --agent sdd-apply
pegasus uninstall --cli opencode
pegasus doctor --json
```

Un test de contrato verifica que cada acción de la TUI tenga su comando equivalente.

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

---

## Postura de seguridad

Todo lo que v3 ya garantiza se mantiene, y se extiende a las dependencias nuevas de Python.

| Garantía | v3 | v4 |
|----------|----|----|
| Instalación aditiva, nunca pisa archivos del usuario | Sí | Sí |
| Payload verificado con SHA-256 | Sí | Sí, sobre el catálogo generado |
| Dependencias con versión fija, sin `npx` ni `latest` | Sí | Sí |
| Sin ejecución como root | Sí | Sí |
| Rollback que preserva lo modificado por el usuario | Sí | Sí, y además restaura |
| Dependencias Python con hashes | — | `pip install --require-hashes` |
| Detección sin ejecutar binarios de terceros | — | Sí |

La verificación de integridad del payload deja de escribirse a mano: el catálogo se genera y CI falla si el catálogo commiteado no coincide con el generado desde el contenido.

---

## Qué queda fuera de 4.0.0

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

Seis unidades. Cada una tiene tests propios y límite de rollback. El detalle de tareas se define aparte.

| # | Unidad | Entrega verificable |
|---|--------|---------------------|
| 0 | Demolición y reubicación | El repositorio queda ordenado, sin motor v3 y sin lógica nueva |
| 1a | Tipos, punteros, códecs, puerto y registry | El motor genérico existe y no conoce ningún CLI |
| 1b | Carga de contenido, adapter OpenCode y catálogo | Genera en memoria el catálogo del contenido presente, con digests deterministas |
| 2 | Motor de instalación, journal v4, rollback | Paridad funcional con v3.1.2 en modo desatendido |
| 3 | Los 12 agentes cableados con sus prompts, y el contenido normalizado | Los 10 SDD existen como subagentes reales |
| 4 | Launcher, venv privado, empaquetado | `pegasus` disponible en el PATH tras instalar |
| 5 | TUI: menú principal e instalación | Instalación completa sin escribir un flag |
| 6 | TUI: configuración de modelos | Asignar y quitar modelo por agente, con mutación registrada |

La unidad 1b genera el catálogo **del contenido presente**, no del contenido final: los descriptores de los 10 agentes SDD y las categorías `mcp/` y `policies/` llegan en unidades posteriores.

El presupuesto de revisión es de **800 líneas cambiadas por PR**. Cada unidad se mide al planificar sus tareas; la que se pase se parte en una cadena, con la estrategia definida antes de empezar a escribir código. La unidad 1 ya se midió y por eso está partida en 1a y 1b; la 2 es la próxima candidata.

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
- [ ] Una mutación sobre un artefacto editado por el usuario pregunta antes de adoptar
- [ ] Un artefacto adoptado se restaura al valor del usuario al desinstalar
- [ ] En modo desatendido, una mutación sobre un artefacto editado no adopta por omisión
- [ ] Desinstalar deja el sistema sin rastros de Pegasus, salvo lo que el usuario modificó

---

## Próximo paso

Revisar y aprobar este documento. Con la aprobación se define el corte en unidades y la estrategia de cadena de PRs, y recién ahí se escribe código.
