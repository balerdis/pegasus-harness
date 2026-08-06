# Aceptación RC v3.1 con cinco perfiles

Esta guía prepara evidencia manual y aislada. No se ejecuta desde tests ni modifica `serg`.

## Camino rápido

1. Elegí un perfil, su usuario mapeado y un RC con archive, checksum y manifest publicados.
2. Ejecutá únicamente el orquestador; valida el RC antes de llamar al provisionador y exige reconocer explícitamente la recreación.
3. Revisá el JSON de evidencia: plan MCP, resultado seleccionado, ausencias/no-orphans, ownership y snapshot de `serg`.

## Perfiles

| Perfil | Cuenta recreada | MCP confirmado | MCP rechazados |
| --- | --- | --- | --- |
| `cbm` | `pegasus-harness` | CBM | Engram, Playwright, Context7 |
| `engram` | `pegasus-harness-engram` | Engram | CBM, Playwright, Context7 |
| `playwright` | `pegasus-harness-playwright` | Playwright | CBM, Engram, Context7 |
| `context7` | `pegasus-harness-context7` | Context7 | CBM, Engram, Playwright |
| `final` | `pegasus-harness-final` | Todos | Ninguno |

## Ejecución

El único punto de entrada es `accept-v3-isolated.sh`. `provision-v3-rc-host.sh` no es un flujo de producto: es el emulador de host de laboratorio que el orquestador invoca después del preflight.

```sh
sudo ./scripts/accept-v3-isolated.sh \
  --profile cbm \
  --rc-archive /releases/pegasus-harness-v3.1.0-rc.1.tar.gz \
  --rc-checksum /releases/pegasus-harness-v3.1.0-rc.1.tar.gz.sha256 \
  --release-manifest /releases/release-manifest.json \
  --staging-dir /var/tmp/pegasus-v3.1.0-rc.1-cbm \
  --evidence-file /var/tmp/pegasus-v3.1.0-rc.1-cbm-evidence.json \
  --confirm-recreate-user pegasus-harness
```

Para Playwright, instalá el navegador externamente en la cuenta recreada antes del apply; Pegasus no lo descarga. Una prueba fallida requiere un commit y RC nuevos: nunca se muta un tag.

## Artefactos verificados

- Node `24.15.0`: descarga oficial Linux x64 y SHA-256 `472655581fb851559730c48763e0c9d3bc25975c59d518003fc0849d3e4ba0f6`; queda en `~/.local/pegasus-acceptance/node`.
- OpenCode: únicamente `opencode-linux-x64@1.18.13`, SRI fijado y launcher propio en `~/.local/bin/opencode`. No usa wrapper `opencode-ai`, npm, postinstall, NVM ni actualización automática.

## Checklist de evidencia

- [ ] Archivo RC, usuario y home dedicado anotados.
- [ ] Checksum y manifest coinciden con el mismo archive RC.
- [ ] SHA/SRI y probes de Node/OpenCode registrados.
- [ ] El resultado contiene únicamente los MCP confirmados; los rechazados no tienen config, dependencia ni ownership huérfanos.
- [ ] Los artifacts de aceptación pertenecen solo al usuario mapeado.
- [ ] Snapshot de `serg` idéntico antes y después.
- [ ] No se descargaron modelos, LSP ni cambios de perfil shell.
