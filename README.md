# Pegasus Harness v2.0.1

Pegasus prepara una configuracion limpia para OpenCode o Claude Code. La preparacion de release es `2.0.1`. Pegasus NO instala OpenCode, CBM ni ninguna dependencia externa: no descarga, no ejecuta instaladores remotos y no usa excepciones para saltear esa regla.

## Antes de instalar

La frontera de confianza es simple: usted obtiene el archivo, checksum y manifest desde un canal autenticado; verifica su integridad; y prepara OpenCode/CBM por fuera de Pegasus, con el procedimiento que usted considere confiable. Recién después Pegasus copia solo sus assets locales verificados a la cuenta indicada.

Para `--client opencode` o `--client all`, la cuenta destino necesita antes:

- OpenCode ejecutable en `~/.opencode/bin/opencode` o `~/.local/bin/opencode`.
- CBM ejecutable en `~/.local/bin/codebase-memory-mcp`.
- Que ambos respondan correctamente a `--version` y `--help`. Pegasus no impone una versión inventada: valida que el binario local sea ejecutable y responda sin mutar nada.

El wrapper se ejecuta como root, exige Python `3.12+`, exige `--target-user` no root y luego opera dentro del home de esa persona con `sudo -u <linux-user> -H`. Los assets quedan bajo propiedad de la cuenta destino. Nunca toma el `PATH` de root para buscar OpenCode o CBM. Si falta un prerrequisito, una sonda falla o el directorio de cliente ya existe, se detiene antes de escribir assets. Si la validación final devuelve error, inspeccione el estado y use `uninstall` antes de reintentar; Pegasus nunca descarga dependencias ni continúa salteando la validación.

## Instalación segura

```sh
sha256sum -c pegasus-harness-v2.0.1.tar.gz.sha256
tar -xzf pegasus-harness-v2.0.1.tar.gz
cd pegasus-harness-v2.0.1
sudo ./install.sh --target-user <linux-user> --client opencode
```

`--client` acepta `opencode`, `claude-code` o `all`. Para preparar un release seguro, primero valide el snapshot, cree un tag anotado sobre ese commit, genere un archivo nuevo y publique juntos archivo, checksum y manifest. El generador no crea tags ni publica assets:

```sh
python3 tools/build_release_manifest.py --tag v2.0.1 --archive dist/pegasus-harness-v2.0.1.tar.gz --output dist/release-manifest.json
```

## Instalacion limpia

Esta version solo admite instalacion limpia. Si la cuenta destino ya tiene configuracion de OpenCode o Claude Code, el instalador se detiene sin modificarla. Limpie manualmente esa configuracion o use una cuenta nueva antes de instalar v2. No existe un camino automatico de actualizacion.

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
