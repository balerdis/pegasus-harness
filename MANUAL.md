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

Si el plan encuentra una clave o un archivo tuyo en el destino, lo informa y lo preserva: no lo adopta como si fuera de Pegasus. El payload de OpenCode queda bajo `~/.config/opencode/` (o el `XDG_CONFIG_HOME` que tengas seteado): las skills en `skills/`, los comandos en `commands/`, el system prompt de Pegasus como `pegasus-AGENTS.md`, y los agentes declarados dentro de `opencode.json` — OpenCode no los materializa como archivos aparte. Después de un apply exitoso, cerrá y reiniciá OpenCode para que cargue la configuración nueva.

## Qué hacen los cuatro MCPs opcionales

| MCP | Uso práctico | Decisión |
| --- | --- | --- |
| CBM (`codebase-memory-mcp`) | Buscar estructura, callers, flujos e impacto de código. | Es inteligencia de código; no prueba comportamiento. |
| Engram | Recuperar decisiones, progreso y resúmenes entre sesiones, con el protocolo de memoria persistente. | La memoria no puede sobreescribir la evidencia actual. |
| Playwright | Probar una frontera de navegador cuando el proyecto lo necesita. | Requiere un navegador compatible instalado por separado; Pegasus no lo descarga. |
| Context7 | Consultar documentación del proveedor de forma remota. | Es el único servidor remoto embarcado; confirmalo por separado. |

Instalá solo lo que el equipo vaya a usar: un servidor no pedido con `--mcp` no deja config ni dependencia huérfana.

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

## Deshacer

- `pegasus restore [generación]` vuelve al estado exacto anterior a un comando (o a una generación puntual del historial de snapshots).
- `pegasus uninstall --cli opencode` retira solo lo que el journal reclama como propio.

El journal vive en `$XDG_DATA_HOME/pegasus-harness/journal-v4.json` (o `~/.local/share/pegasus-harness/journal-v4.json`), en un directorio `0700` con el archivo en `0600`. Un ítem que editaste vos, o que ya no puede probarse como propio de Pegasus, se preserva: nunca uses `restore` ni `uninstall` para borrar configuración que ya era tuya.

## Próximo paso

- Para el recorrido completo de instalación: [INSTALL.md](INSTALL.md).
- Para instalación asistida por un agente: [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md).
- Para la arquitectura y las decisiones de diseño de v4: [docs/pegasus-v4/arquitectura.md](docs/pegasus-v4/arquitectura.md).
