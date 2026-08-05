# Pegasus Harness v2

Pegasus Harness v2 instala una configuracion limpia y autocontenida para OpenCode o Claude Code. La version de preparacion es `2.0.0`.

## Camino rapido

1. Descargue un archivo de release, su checksum y verifique ambos desde un canal autenticado.
2. Extraiga el archivo y ejecute el instalador como root para una cuenta Linux no root.
3. Reinicie OpenCode despues de instalar para cargar la configuracion nueva.

```sh
sha256sum -c pegasus-harness-v2.0.0.tar.gz.sha256
tar -xzf pegasus-harness-v2.0.0.tar.gz
cd pegasus-harness-v2.0.0
sudo ./install.sh --target-user <linux-user> --client all
```

`--client` acepta `opencode`, `claude-code` o `all`. El wrapper requiere Python 3.12+, valida la cuenta destino y ejecuta Pegasus dentro de su home mediante `sudo -u <linux-user> -H`.

## Cambio incompatible

Esta version solo admite instalacion limpia. Si la cuenta destino ya tiene configuracion de OpenCode o Claude Code, el instalador se detiene sin modificarla. Limpie manualmente esa configuracion o use una cuenta nueva antes de instalar v2. No existe un camino automatico de actualizacion.

## Arquitectura

- `source/core/skills/`: skills canonicos y sus referencias.
- `source/opencode/`: configuracion, agente y comando de verificacion.
- `source/adapters/`: adaptador sin plugins para Claude Code.
- `tools/`: validadores, generador de registro y herramienta de archivo de release.
- `manifests/`: contrato e integridad del release.

CBM es obligatorio para descubrir estructura de codigo, analizar callers y flujos, medir impacto y elegir tests cuando aplique. Es inteligencia de codigo, no prueba de comportamiento: las pruebas y los checks de ejecucion aportan esa evidencia. La busqueda directa queda reservada para literales, archivos no-codigo, configuracion, grafo sin indice o desactualizado, o falla de CBM.

Para cambios ejecutables o de configuracion, `sdd-verify` es la unica autoridad de readiness.

## Verificacion local

```sh
python3 tools/validate_snapshot.py
python3 -m unittest discover -s tests
python3 -m py_compile bin/pegasus tools/*.py
bash -n install.sh
```

La instalacion no incluye credenciales. Configure proveedores y servicios externos con el mecanismo seguro de la cuenta destino.

Consulte [la guia de instalacion limpia](docs/instalacion-limpia-v2.md) y [la distribucion de releases](docs/release-distribution.md).
