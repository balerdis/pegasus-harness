# Pegasus Harness v3.1

Pegasus Harness es un conjunto open source con licencia MIT de prompts, agentes, skills, comandos e integraciones opcionales para trabajar con OpenCode de forma más ordenada. Sirve para distintos clientes y repositorios: el flujo queda en manos del equipo que lo usa, no de una configuración particular de cliente.

Pegasus es aditivo. Revisa lo que ya existe, muestra un plan y crea solamente los artifacts seleccionados que faltan. No toma propiedad de una instalación existente de OpenCode, su configuración ni sus archivos.

> Este repositorio documenta la línea v3.1. No afirma que se haya publicado un release final `v3.1.0`.

## Camino rápido

1. Siga [INSTALL.md](INSTALL.md) para preparar OpenCode y elegir proveedor/modelo en la cuenta destino, por fuera de Pegasus.
2. Verifique el archive y checksum obtenidos desde su canal confiable; después extraiga el archive y valide el snapshot.
3. Revise el plan, confirme solamente los MCPs que va a usar y reinicie OpenCode después de un apply exitoso.

```sh
sha256sum -c pegasus-harness-v3.1.0-rc.N.tar.gz.sha256
tar -xzf pegasus-harness-v3.1.0-rc.N.tar.gz
cd pegasus-harness-v3.1.0-rc.N
sudo ./install.sh --target-user <linux-user> --client opencode \
  --decline cbm --decline engram --decline playwright --decline context7
```

El último comando es un ejemplo sin MCPs opcionales. Revise el plan y reemplace cada `--decline` solo cuando haya decidido confirmar esa dependencia.

## Lo que sigue bajo su control

| Tema | Cómo trabaja Pegasus |
| --- | --- |
| OpenCode | Usted instala, actualiza y configura el cliente anfitrión. Pegasus no lo hace por usted. |
| Archivos y claves de configuración existentes | Se detectan y se preservan. Un collision se informa; no se sobreescribe. |
| MCPs opcionales | Cada MCP faltante requiere su propia confirmación. Rechazarlo no deja descarga, clave de configuración ni huérfano. |
| Credenciales, proveedores y modelos | Nunca se distribuyen ni se imponen acá. La persona configura las credenciales del proveedor con `/connect` y selecciona el modelo con `/models`. |
| Rollback | El comando `uninstall` elimina solamente artifacts sin cambios que Pegasus creó y registró en su journal. |

El límite completo de distribución está en [docs/contrato-inclusion-artifacts.md](docs/contrato-inclusion-artifacts.md). El procedimiento práctico de instalación aditiva y rollback está en [docs/instalacion-aditiva-v3.md](docs/instalacion-aditiva-v3.md).

## Qué incluye

Pegasus distribuye un payload seleccionado para OpenCode, no un home directory de reemplazo:

- commands para SDD, contexto, handoff, creación y registro de skills;
- el orquestador de Pegasus y sus roles de implementación/verificación;
- skills reutilizables y sus referencias;
- plugins locales seleccionados y, solo si se confirman, las integraciones opcionales CBM, Engram, Playwright y Context7.

El source queda a la vista: los prompts están en `source/opencode/prompts/`, las instrucciones del orquestador en `source/opencode/agents/`, las skills en `source/core/skills/` y las claves de OpenCode distribuidas en `source/opencode/opencode.json`. Puede revisar esos archivos antes de aplicar algo y adaptar las instrucciones de su proyecto sin volver Pegasus específico de un cliente.

## Cómo encaja el flujo

La versión corta es: primero entender, después especificar, implementar por unidades chicas y probar el resultado. [architecture.md](architecture.md) explica las responsabilidades de SDD, TDD, OpenSpec, Engram y ChainPR sin esconder los límites operativos.

Para cambios ejecutables o de configuración, `sdd-verify` es la autoridad final de readiness. CBM ayuda a descubrir estructura y callers; no reemplaza una prueba de comportamiento que pasó.

## Prerrequisitos de OpenCode

Para `--client opencode`, la cuenta destino necesita tener OpenCode instalado antes de ejecutar Pegasus. El wrapper también requiere Python 3.12+, una cuenta destino no-root y acceso `sudo` para entrar en esa cuenta. Para CBM, el ejecutable local debe responder a `--version` y `--help`; Playwright necesita un navegador compatible instalado externamente antes del apply.

[INSTALL.md](INSTALL.md) tiene el flujo probado de cuenta separada; [MANUAL.md](MANUAL.md) cubre los pre-chequeos y el uso diario. Pegasus no configura credenciales, proveedor ni modelo: en el primer uso configurá las credenciales del proveedor con `/connect` y seleccioná el modelo con `/models`.

## Validar un checkout

```sh
python3 tools/validate_snapshot.py
python3 -m unittest discover -s tests
python3 -m py_compile bin/pegasus tools/*.py
bash -n install.sh
```

Estos checks validan este checkout. No instalan OpenCode, no cambian una cuenta destino y no ejecutan la aceptación RC aislada.

## Notas de release y aceptación

La promoción de release es una operación manual separada. Un archive inmutable `v3.1.0-rc.N`, su checksum y su manifest pasan por la matriz aislada de cinco perfiles antes de que pueda crearse un tag final inmutable. Un fallo exige commit nuevo y RC nuevo; los tags no se mueven.

Consulte [docs/release-distribution.md](docs/release-distribution.md) y [docs/aceptacion-rc-v3.1.md](docs/aceptacion-rc-v3.1.md) si queda a cargo de ese trabajo.

## Licencia

Pegasus Harness se distribuye bajo la [licencia MIT](LICENSE).
