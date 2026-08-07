# Aceptación RC v3.1 con cinco perfiles

Esta guía prepara evidencia manual y aislada. No se ejecuta desde tests ni modifica `serg`.

## Camino rápido

1. Elegí un perfil, su usuario mapeado y un RC con archive, checksum y manifest publicados.
2. Prepará un directorio de evidencia root-controlado fuera de `/home` y delegá lectura, nunca escritura, al verificador no-root `serg`.
3. Ejecutá únicamente el orquestador; valida el RC antes de llamar al provisionador y exige reconocer explícitamente la recreación.
4. Ejecutá el verificador como `serg` con una salida privada separada; su único `PASS` agregado es entrada del gate de promoción, no crea tags ni releases.

## Perfiles

| Perfil | Cuenta recreada | MCP confirmado | MCP rechazados |
| --- | --- | --- | --- |
| `cbm` | `pegasus-harness` | CBM | Engram, Playwright, Context7 |
| `engram` | `pegasus-harness-engram` | Engram | CBM, Playwright, Context7 |
| `playwright` | `pegasus-harness-playwright` | Playwright | CBM, Engram, Context7 |
| `context7` | `pegasus-harness-context7` | Context7 | CBM, Engram, Playwright |
| `final` | `pegasus-harness-final` | Todos | Ninguno |

## Ejecución

El único punto de entrada es `accept-v3-isolated.sh`. `provision-v3-rc-host.sh` no es un flujo de producto: es el emulador de host de laboratorio que el orquestador invoca después del preflight. Root extrae y verifica el RC en el staging privado; después entrega una copia nueva bajo `/var/lib/pegasus-acceptance/<target>/rc`, cuyos ancestros son root-owned y no admiten escritura del target. El payload permanece `root:<grupo primario del target>` con directorios y `bin/pegasus` en `0750`, otros archivos en `0640`: el target puede recorrer, leer y ejecutar el payload verificado, pero no reemplazarlo; no es legible globalmente.

Antes del primer perfil, prepará una vez el handoff de evidencia. `serg` es el verificador no-root documentado: recibe sólo lectura por grupo; no se modifica su home ni su configuración. El directorio queda `root:<grupo-primario-de-serg> 0750`, y cada JSON queda `root:<grupo-primario-de-serg> 0640`. Así `serg` puede leer los cinco registros, pero no crear, borrar ni reemplazar ninguno; no hay permisos globales.

```sh
sudo install -d -o root -g "$(id -g serg)" -m 0750 /var/lib/pegasus-acceptance-evidence/v3.1.0-rc.1
sudo -n -u serg -H install -d -m 0700 /var/tmp/pegasus-v3.1.0-rc.1-aggregate-serg
```

La segunda orden se ejecuta explícitamente como `serg`: no la ejecutes como root, porque el verificador exige que su directorio de salida `0700` le pertenezca.

```sh
sudo ./scripts/accept-v3-isolated.sh \
  --profile cbm \
  --rc-archive /releases/pegasus-harness-v3.1.0-rc.1.tar.gz \
  --rc-checksum /releases/pegasus-harness-v3.1.0-rc.1.tar.gz.sha256 \
  --release-manifest /releases/release-manifest.json \
  --staging-dir /var/tmp/pegasus-v3.1.0-rc.1-cbm \
  --evidence-file /var/lib/pegasus-acceptance-evidence/v3.1.0-rc.1/cbm.json \
  --evidence-verifier serg \
  --confirm-recreate-user pegasus-harness
```

Para Playwright, instalá el navegador externamente; Pegasus no lo descarga. Se puede pasar `--browser <ruta-absoluta>` al orquestador, que lo propaga al provisionador y al preflight. La ruta debe ser un ejecutable regular, no symlink, root-owned, sin escritura grupal/global y fuera del home objetivo; todos sus ancestros deben cumplir la misma propiedad y permisos. Si se omite, se conserva la detección existente en `~/.cache/ms-playwright/chromium` y `~/.local/bin/chromium`. Una prueba fallida requiere un commit y RC nuevos: nunca se muta un tag.

## Artefactos verificados

- Node `24.15.0`: descarga oficial Linux x64 y SHA-256 `472655581fb851559730c48763e0c9d3bc25975c59d518003fc0849d3e4ba0f6`; queda en `~/.local/pegasus-acceptance/node`.
- OpenCode: únicamente `opencode-linux-x64@1.18.13`, SRI fijado y launcher propio en `~/.local/bin/opencode`. No usa wrapper `opencode-ai`, npm, postinstall, NVM ni actualización automática.

## Gate de matriz

Luego de ejecutar los cinco perfiles contra el mismo archive RC, checksum y manifest, guardá exactamente sus cinco evidencias JSON en ese directorio root-controlado fuera de `/home`, pasando siempre `--evidence-verifier serg`. Cada evidencia emitida por el orquestador incluye `rc.tag`, nombre y SHA-256 del archive, SHA-256 del checksum, SHA-256 del manifest y `archive_root`; esa identidad debe ser idéntica en toda la matriz.

```sh
sudo -n -u serg -H python3 ./scripts/verify-v3-acceptance-matrix.py \
  --rc-archive /releases/pegasus-harness-v3.1.0-rc.1.tar.gz \
  --rc-checksum /releases/pegasus-harness-v3.1.0-rc.1.tar.gz.sha256 \
  --release-manifest /releases/release-manifest.json \
  --evidence-dir /var/lib/pegasus-acceptance-evidence/v3.1.0-rc.1 \
  --output-file /var/tmp/pegasus-v3.1.0-rc.1-aggregate-serg/rc-acceptance-aggregate.json
```

El verificador es test-only y no invoca provisionamiento, aceptación, creación de usuarios, tags, releases ni Pegasus. Rechaza paths inseguros, JSON inválido, perfiles faltantes o duplicados, cualquier resultado distinto de `PASS` y cualquier identidad RC distinta. Escribe `rc-acceptance-aggregate.json` sólo en el directorio privado `0700` de salida de `serg`, separado del directorio root-controlado de evidencia. No lo ejecutes otra vez sobre el mismo archivo: la salida existente se rechaza para conservar una única evidencia de promoción.

## Checklist de evidencia

- [ ] Archivo RC, usuario y home dedicado anotados.
- [ ] Checksum y manifest coinciden con el mismo archive RC.
- [ ] SHA/SRI y probes de Node/OpenCode registrados.
- [ ] El resultado contiene únicamente los MCP confirmados; los rechazados no tienen config, dependencia ni ownership huérfanos.
- [ ] Los artifacts de aceptación pertenecen solo al usuario mapeado.
- [ ] El payload de handoff está bajo `/var/lib/pegasus-acceptance/<target>/rc`; todos sus ancestros son root-owned sin escritura grupal/global, y el payload es `root:<grupo del target>` (`0750` directorios/entrypoint, `0640` otros archivos), sin lectura global.
- [ ] Snapshot de `serg` idéntico antes y después.
- [ ] No se descargaron modelos, LSP ni cambios de perfil shell.
- [ ] Hay exactamente una evidencia `PASS` de cada perfil y las cinco tienen la misma identidad RC.
- [ ] Cada JSON es `root:<grupo de serg> 0640` bajo un directorio `root:<grupo de serg> 0750`; `serg` puede leerlos y no puede mutarlos.
- [ ] `rc-acceptance-aggregate.json` fue generado por `serg` en su directorio privado de salida antes del tag final.
