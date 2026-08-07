# Instalar Pegasus en la cuenta Linux actual

Este recorrido instala Pegasus para la persona que está usando la terminal. No uses `sudo` ni apuntes a otra cuenta: Pegasus agrega artifacts a tu `~/.config` y `~/.local` sin reemplazar lo que ya existe.

## 1. Prerrequisitos

Necesitás Python 3.12+ y OpenCode en esta cuenta. Si OpenCode todavía no está disponible, instalalo con el procedimiento oficial como tu usuario actual y verificá el binario:

```sh
curl -fsSL https://opencode.ai/install | bash
opencode --version
```

Si la instalación oficial no deja `opencode` en `PATH`, abrí una shell nueva o seguí la indicación que muestra el instalador oficial antes de continuar.

Si pensás confirmar CBM, verificá también su ejecutable local con `codebase-memory-mcp --version` y `codebase-memory-mcp --help`. Para Playwright, instalá un navegador compatible por separado antes de confirmarlo.

## 2. Trabajar desde un checkout verificado

Usá un checkout o archive que hayas verificado. Para un archive, comprobá su checksum antes de extraerlo; en ambos casos, validá el snapshot desde la raíz del checkout:

```sh
sha256sum -c pegasus-harness.tar.gz.sha256
tar -xzf pegasus-harness.tar.gz
cd pegasus-harness
python3 tools/validate_snapshot.py
```

Continuá solamente si el checksum termina en `OK` y el validador termina en `PASS`.

## 3. Ejecutar el instalador

Desde ese checkout, ejecutá el wrapper como tu usuario actual. Primero muestra y valida el plan; solo después ejecuta el apply.

Cada MCP faltante recibe una única decisión: `--confirm <mcp>` lo instala o configura, y `--decline <mcp>` no lo descarga, configura ni registra. No omitas decisiones para MCPs faltantes.

Este ejemplo confirma Context7 y rechaza los otros MCPs opcionales:

```sh
./install.sh --client opencode \
  --confirm context7 \
  --decline cbm --decline engram --decline playwright
```

## 4. Verificar y configurar OpenCode

```sh
opencode debug config
opencode debug info
test -f "$HOME/.local/share/pegasus-harness/journal-v3.json" && printf '%s\n' 'journal de Pegasus presente'
opencode
```

Dentro de OpenCode, ejecutá `/connect` para configurar las credenciales del proveedor y `/models` para elegir el modelo. Pegasus no maneja ninguno de los dos.

## Lo que sigue bajo su control

| Tema | Cómo trabaja Pegasus |
| --- | --- |
| OpenCode | Usted instala, actualiza y configura el cliente anfitrión. Pegasus no lo hace por usted. |
| Archivos y claves de configuración existentes | Se detectan y se preservan. Un collision se informa; no se sobreescribe. |
| MCPs opcionales | Cada MCP faltante requiere su propia confirmación. Rechazarlo no deja descarga, clave de configuración ni huérfano. |
| Credenciales, proveedores y modelos | Nunca se distribuyen ni se imponen acá. La persona configura las credenciales del proveedor con /connect y selecciona el modelo con /models. |
| Rollback | El comando uninstall elimina solamente artifacts sin cambios que Pegasus creó y registró en su journal. |

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para la política de ownership y rollback, consultá [docs/instalacion-aditiva-v3.md](docs/instalacion-aditiva-v3.md).

Si un agente te asiste, usá el preflight read-only y el registro de decisiones de [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) antes de recibir comandos de apply. Esa guía no lee ni imprime tu configuración o credenciales de OpenCode.
