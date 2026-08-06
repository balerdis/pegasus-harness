# Pegasus Harness v3.1.0

Pegasus suma artifacts seleccionados a una instalación existente de OpenCode o Claude Code. La línea de release es `3.1.0`: no reemplaza directorios, archivos ni claves de usuario, y no toma propiedad de lo que ya existía.

## Camino rápido

1. Lea el plan: `sudo ./install.sh --target-user <linux-user> --client opencode`.
2. Revise cada dependencia ausente y confirme o rechace individualmente con `--confirm` o `--decline`.
3. Reinicie OpenCode después de una aplicación exitosa: su configuración se carga al inicio.

La guía completa, migración y aceptación aislada están en [instalación aditiva v3](docs/instalacion-aditiva-v3.md).

## Antes de instalar

La frontera de confianza es simple: usted obtiene el archivo, checksum y manifest desde un canal autenticado; verifica su integridad; y prepara OpenCode/CBM por fuera de Pegasus, con el procedimiento que usted considere confiable. Recién después Pegasus copia solo sus assets locales verificados a la cuenta indicada.

Para `--client opencode` o `--client all`, la cuenta destino necesita OpenCode instalado por fuera de Pegasus. Para Playwright también necesita un navegador compatible instalado externamente antes del apply.

- OpenCode ejecutable en `~/.opencode/bin/opencode` o `~/.local/bin/opencode`.
- CBM ejecutable en `~/.local/bin/codebase-memory-mcp`.
- Que ambos respondan correctamente a `--version` y `--help`. Pegasus no impone una versión inventada: valida que el binario local sea ejecutable y responda sin mutar nada.

El wrapper se ejecuta como root, exige Python `3.12+`, exige `--target-user` no root y luego opera dentro del home de esa persona con `sudo -u <linux-user> -H`. Los assets quedan bajo propiedad de la cuenta destino. Nunca toma el `PATH` de root para buscar OpenCode o CBM. Si falta un prerrequisito, una sonda falla o el directorio de cliente ya existe, se detiene antes de escribir assets. Si la validación final devuelve error, inspeccione el estado y use `uninstall` antes de reintentar; Pegasus nunca descarga dependencias ni continúa salteando la validación.

## Instalación segura

```sh
sha256sum -c pegasus-harness-v3.1.0.tar.gz.sha256
tar -xzf pegasus-harness-v3.1.0.tar.gz
cd pegasus-harness-v3.1.0
sudo ./install.sh --target-user <linux-user> --client opencode --decline cbm --decline engram --decline playwright
```

`--client` acepta `opencode`, `claude-code` o `all`. Para preparar un release seguro, primero valide el snapshot, cree un tag anotado sobre ese commit, genere un archivo nuevo y publique juntos archivo, checksum y manifest. El generador no crea tags ni publica assets:

```sh
python3 tools/build_release_manifest.py --tag v3.1.0-rc.1 --archive dist/pegasus-harness-v3.1.0-rc.1.tar.gz --output dist/release-manifest.json
```

## Migración desde v2

El estado v2 es ambiguo. v3 lo informa, no lo adopta, no lo reescribe y no lo elimina. Los collisions se preservan y el journal v3 solo registra creaciones verificables.

## Arquitectura

- `source/core/skills/`: skills canonicos y sus referencias.
- `source/opencode/`: configuracion, agente y comando de verificacion.
- `source/adapters/`: adaptador sin plugins para Claude Code.
- `tools/`: validadores, generador de registro y herramienta de archivo de release.
- `manifests/`: contrato e integridad del release.

CBM es obligatorio para descubrir estructura de codigo, analizar callers y flujos, medir impacto y elegir tests cuando aplique. Es inteligencia de codigo, no prueba de comportamiento: las pruebas y los checks de ejecucion aportan esa evidencia. La busqueda directa queda reservada para literales, archivos no-codigo, configuracion, grafo sin indice o desactualizado, o falla de CBM.

Para cambios ejecutables o de configuracion, `sdd-verify` es la unica autoridad de readiness.

## Validacion local

```sh
python3 tools/validate_snapshot.py
python3 -m unittest discover -s tests
python3 -m py_compile bin/pegasus tools/*.py
bash -n install.sh
```

La instalacion no incluye credenciales. Configure proveedores y servicios externos con el mecanismo seguro de la cuenta destino. Después, reinicie OpenCode: lee su configuración al iniciar.

Consulte [la guia de instalacion limpia](docs/instalacion-limpia-v2.md) y [la distribucion de releases](docs/release-distribution.md).
