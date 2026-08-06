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

Este procedimiento es manual y posterior al release. Ningún test ejecuta los scripts ni crea, borra, resetea o reutiliza usuarios. El laboratorio no es código de producto: Pegasus no lo instala, no lo cataloga ni lo registra como ownership.

### Procedimiento exacto: RC a tag final

1. Valide el commit y cree un tag anotado e inmutable `v3.1.0-rc.N`. Genere y publique juntos el archive RC, su `.sha256` y `release-manifest.json`. El tag final `v3.1.0` NO se crea en este paso.
2. Seleccione uno de los cinco perfiles documentados en [la matriz RC](aceptacion-rc-v3.1.md#perfiles). El orquestador deriva el único usuario permitido y exige `--confirm-recreate-user` con ese nombre exacto; protege `serg`, root, homes inseguros, perfiles desconocidos y archives no RC.
3. El orquestador valida archive, checksum y manifest antes de invocar el emulador de host. El emulador recrea únicamente el usuario mapeado e instala Node `24.15.0` y OpenCode `1.18.13` dentro de ese home. No reutiliza binarios, cachés, HOME, XDG ni configuración de `serg`.
4. Desde un checkout del mismo tag RC, ejecute como root con rutas explícitas nuevas para staging y evidencia:

```sh
sha256sum -c /releases/pegasus-harness-v3.1.0-rc.1.tar.gz.sha256
sudo ./scripts/accept-v3-isolated.sh \
  --profile cbm \
  --rc-archive /releases/pegasus-harness-v3.1.0-rc.1.tar.gz \
  --rc-checksum /releases/pegasus-harness-v3.1.0-rc.1.tar.gz.sha256 \
  --release-manifest /releases/release-manifest.json \
  --staging-dir /var/tmp/pegasus-v3.1.0-rc.1-acceptance \
  --evidence-file /var/tmp/pegasus-v3.1.0-rc.1-evidence.json \
  --confirm-recreate-user pegasus-harness
```

5. El script rechaza tags finales/no RC, profiles desconocidos, acknowledgement incorrecto, archivos/checksum/manifest inconsistentes, staging/evidence preexistentes y paths/homes inseguros. Después extrae el archive validado, llama al provisionador y ejecuta plan/apply/validate con el plan explícito del perfil. Verifica MCP seleccionado, MCP rechazados sin config/dependencia/ownership huérfano, ownership del usuario mapeado y el snapshot final de `serg`.
6. Repita el paso para los cinco perfiles y guarde los JSON en un directorio nuevo fuera de `/home`. Cada registro debe contener `status: "PASS"`, el `profile` esperado, el journal y la misma identidad RC canónica: tag, nombre/SHA-256 del archive, SHA-256 del checksum, SHA-256 del manifest y `archive_root`.
7. Ejecute `python3 scripts/verify-v3-acceptance-matrix.py --rc-archive <archive> --rc-checksum <checksum> --release-manifest <manifest> --evidence-dir <directorio-nuevo-fuera-de-home>`. El gate rechaza faltantes, duplicados, JSON inválido, perfiles fallidos, identidad RC diferente y paths inseguros. Solo su único `rc-acceptance-aggregate.json` con `status: "PASS"` habilita crear el tag anotado e inmutable `v3.1.0` sobre el mismo commit. No crea tags ni releases. Si falla cualquier paso, corrija en un commit nuevo y cree otro `v3.1.0-rc.N`; nunca mueva un tag RC ni el tag final.

El resultado esperado es `PASS`, artifacts pertenecientes a la cuenta dedicada, evidencia persistida y ningún cambio en la instalación activa de `serg`.

### Límite de rollback

El rollback normal termina en `pegasus uninstall`: solo elimina artifacts registrados en `journal-v3.json` que mantengan su baseline. La carpeta `notifier/node_modules` pertenece exclusivamente a esta aceptación de home limpio y queda fuera del journal; si se necesita descartar la aceptación, elimínela manualmente solo después de confirmar que sigue bajo `/home/pegasus-harness/.config/opencode/notifier/`. Nunca use ese rollback para borrar o modificar archivos de `serg` ni artifacts preexistentes del usuario.
