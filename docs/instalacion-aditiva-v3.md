# Instalación aditiva v3

Pegasus v3 agrega únicamente los artifacts del catálogo. No reemplaza archivos, claves JSON ni directorios existentes; un collision se informa y queda bajo control del usuario.

## Camino rápido

1. Verifique el archivo de release y ejecute `python3 tools/validate_snapshot.py`.
2. Muestre el plan: `sudo ./install.sh --target-user <linux-user> --client opencode`.
3. Confirme cada MCP ausente explícitamente o rechácelo. Ejemplo sin dependencias: `--decline cbm --decline engram --decline playwright`.
4. Si falta el navegador de Playwright, cancele. Instálelo externamente y vuelva a ejecutar el plan; Pegasus no descarga navegadores.

## Propiedad y reversión

El journal en `~/.local/share/pegasus-harness/journal-v3.json` registra cada creación con release, origen, digest y baseline. `uninstall` elimina solo una entrada cuyo baseline sigue igual. Si hubo una edición o el journal es incierto, la preserva.

## Aceptación aislada de mantenimiento

Este procedimiento es manual y posterior al release. Ningún test ejecuta el script, ni crea, borra, resetea o reutiliza `/home/pegasus-harness`.

### Procedimiento exacto: RC a tag final

1. Valide el commit y cree un tag anotado e inmutable `v3.1.0-rc.N`. Genere y publique juntos el archive RC, su `.sha256` y `release-manifest.json`. El tag final `v3.1.0` NO se crea en este paso.
2. Cree previamente la cuenta Linux dedicada `pegasus-harness` con home exacto `/home/pegasus-harness`. El home debe estar vacío, ser un directorio real y pertenecer a esa cuenta. El script se niega a limpiar o reutilizar un home con contenido.
3. Instale OpenCode y npm exclusivamente dentro de esa cuenta. No reutilice binarios, cachés, HOME, XDG ni configuración de `serg`.
4. Desde un checkout del mismo tag RC, verifique el checksum del archive y ejecute como root con rutas explícitas nuevas para staging y evidencia:

```sh
sha256sum -c /releases/pegasus-harness-v3.1.0-rc.1.tar.gz.sha256
sudo ./scripts/accept-v3-isolated.sh \
  --rc-tag v3.1.0-rc.1 \
  --archive /releases/pegasus-harness-v3.1.0-rc.1.tar.gz \
  --release-manifest /releases/release-manifest.json \
  --staging-dir /var/tmp/pegasus-v3.1.0-rc.1-acceptance \
  --evidence-file /var/tmp/pegasus-v3.1.0-rc.1-evidence.json \
  --target-user pegasus-harness \
  --confirm-clean-home
```

5. El script rechaza tags finales/no RC, archivos o manifest inconsistentes, CBM sin digest/provenance coincidente, staging/evidence preexistentes, home no vacío y ownership incorrecto. Después extrae el archive validado, ejecuta plan/apply/validate con CBM, Engram, Playwright y Context7 rechazados, instala el notifier bloqueado con `npm ci --ignore-scripts`, verifica journal/ownership/no-overwrite y compara el snapshot final de `serg`.
6. Revise el JSON de evidencia. Solo si contiene `status: "PASS"`, el mismo `rc_tag`, el SHA-256 del archive publicado y el journal esperado, cree el tag anotado e inmutable `v3.1.0` sobre el mismo commit. Si falla cualquier paso, corrija en un commit nuevo y cree otro `v3.1.0-rc.N`; nunca mueva un tag RC ni el tag final.

El resultado esperado es `PASS`, artifacts pertenecientes a la cuenta dedicada, evidencia persistida y ningún cambio en la instalación activa de `serg`.

### Límite de rollback

El rollback normal termina en `pegasus uninstall`: solo elimina artifacts registrados en `journal-v3.json` que mantengan su baseline. La carpeta `notifier/node_modules` pertenece exclusivamente a esta aceptación de home limpio y queda fuera del journal; si se necesita descartar la aceptación, elimínela manualmente solo después de confirmar que sigue bajo `/home/pegasus-harness/.config/opencode/notifier/`. Nunca use ese rollback para borrar o modificar archivos de `serg` ni artifacts preexistentes del usuario.
