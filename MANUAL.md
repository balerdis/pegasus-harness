# Manual de adopción: OpenCode + Pegasus Harness

Este manual sirve para preparar OpenCode y sumar Pegasus sin entregar el control de tu cuenta o de tus proyectos. OpenCode es el cliente anfitrión; Pegasus agrega un payload seleccionado y preserva lo que ya tenías.

## Antes de empezar

Necesitás una cuenta Linux no-root para usar como destino y permisos para ejecutar `sudo` hacia esa cuenta. Pegasus corre el wrapper como root, pero el trabajo de aplicación ocurre dentro del home de la persona indicada.

| Requisito | Cómo comprobarlo | Para qué sirve |
| --- | --- | --- |
| OpenCode instalado por fuera de Pegasus | `~/.opencode/bin/opencode --version` o `~/.local/bin/opencode --version` | El cliente anfitrión no se instala desde este repo. |
| Python 3.12 o superior | `python3 --version` | Ejecuta el motor de Pegasus. |
| `sudo` | `sudo -n -u <linux-user> -H true` | Permite entrar de forma explícita a la cuenta destino. |
| CBM, si lo vas a usar | `~/.local/bin/codebase-memory-mcp --version` y `--help` | Pegasus valida que el binario local responda antes de configurarlo. |
| Navegador compatible, si confirmás Playwright | revisión externa antes de apply | Pegasus no descarga navegadores. |

No uses root como `--target-user`. No corras Pegasus sobre una cuenta que no querés que reciba sus propios artifacts en `~/.config` y `~/.local`.

## Instalar OpenCode

Instalá OpenCode con el método oficial que prefieras, fuera de Pegasus. Por ejemplo, el instalador oficial publica esta alternativa:

```sh
curl -fsSL https://opencode.ai/install | bash
```

También existe instalación con Homebrew o gestores de paquetes de Node. Elegí una sola vía, verificá la versión con el binario que quedó en tu cuenta y seguí el mecanismo oficial para actualizarlo. Pegasus no instala, actualiza ni desinstala OpenCode.

Después ubicá el ejecutable en una de las rutas que valida el release:

```sh
~/.opencode/bin/opencode --version
# o
~/.local/bin/opencode --version
```

## Aplicar Pegasus de forma aditiva

Primero trabajá sobre un archive verificado y revisá el plan. El comando siempre imprime el plan antes de aplicar.

```sh
sha256sum -c pegasus-harness-v3.1.0-rc.N.tar.gz.sha256
tar -xzf pegasus-harness-v3.1.0-rc.N.tar.gz
cd pegasus-harness-v3.1.0-rc.N

sudo ./install.sh --target-user <linux-user> --client opencode \
  --decline cbm --decline engram --decline playwright --decline context7
```

Para habilitar una integración ausente, cambiá solo esa decisión por `--confirm <nombre>` después de revisar su origen y la acción mostrada en el plan. Los nombres admitidos son `cbm`, `engram`, `playwright` y `context7`.

Ejemplo: confirmar CBM y rechazar el resto.

```sh
sudo ./install.sh --target-user <linux-user> --client opencode \
  --confirm cbm \
  --decline engram --decline playwright --decline context7
```

Si el plan encuentra una clave o un archivo tuyo en el destino, lo informa y lo preserva. No lo adopta como si fuera de Pegasus. Si la validación final falla, inspeccioná el estado y usá el uninstall/journal de Pegasus antes de volver a intentar; no fuerces un segundo apply sobre un estado incierto.

## Usarlo todos los días

1. Abrí OpenCode dentro del repositorio en el que vas a trabajar.
2. Para un cambio con alcance real, iniciá el flujo SDD y completá el pre-chequeo de sesión que pide el orquestador.
3. Dejá que explore, propuesta, spec, diseño y tareas aclaren el cambio antes de apply.
4. Implementá por unidades de trabajo y cerrá con `sdd-verify` cuando estén completas las tareas.

Los comandos distribuidos incluyen `sdd-init`, `sdd-new`, `sdd-ff`, `sdd-apply`, `sdd-status`, `sdd-verify`, `sdd-archive`, además de comandos de contexto, handoff y registry. Los prompts y las reglas de cada fase son parte del payload; podés leerlos en `source/opencode/commands/` y `source/opencode/prompts/` antes de usarlos.

Para revisar la configuración efectiva de OpenCode después de reiniciarlo, la CLI actual ofrece:

```sh
opencode debug config
opencode debug info
```

Eso sirve para mirar la configuración resuelta y los plugins que OpenCode reconoce. No reemplaza las validaciones de Pegasus ni una prueba de comportamiento.

## Configurar modelo por agente

El payload v3.1 trae sus agentes en la clave `agent` de `~/.config/opencode/opencode.json`. Cada agente tiene su propio campo `model`; no hay que cambiar el modelo de todos para probar uno solo.

La configuración distribuida hoy usa estos roles:

| Agente | Rol | Modelo distribuido |
| --- | --- | --- |
| `pegasus-orchestrator` | Coordina las fases SDD. | `openai/gpt-5.6-terra` |
| `king-gentleman` | Agente de implementación general. | `openai/gpt-5.6-terra` |
| `sdd-verify` | Verificación independiente de cambios ejecutables/configurables. | `openai/gpt-5.6-terra` |

Ejemplo de cambio puntual sobre una copia de tu configuración:

```json
{
  "agent": {
    "king-gentleman": {
      "model": "provider/model-id"
    }
  }
}
```

Usá el identificador que soporte tu proveedor y configurá sus credenciales por el mecanismo seguro de tu cuenta. No pongas tokens en el repo, prompts, comandos ni archivos que vayan a versionarse. Antes de editar, hacé una copia de tu `opencode.json`; después reiniciá OpenCode y revisá `opencode debug config`.

Importante: Pegasus preserva una clave existente cuando ve un collision. Si ya tenías `agent` o una configuración equivalente, el apply no la pisa para imponerte estos modelos. En ese caso, la decisión de incorporar o adaptar los roles es tuya.

## Qué hacen los MCPs opcionales

| MCP | Uso práctico | Decisión |
| --- | --- | --- |
| CBM | Buscar estructura, callers, flujos e impacto de código. | Es inteligencia de código; no prueba comportamiento. |
| Engram | Recuperar decisiones, progreso y resúmenes entre sesiones. | La memoria no puede sobreescribir la evidencia actual. |
| Playwright | Probar una frontera de navegador cuando el proyecto lo necesita. | Requiere navegador externo y su pre-chequeo. |
| Context7 | Consultar documentación del proveedor de forma remota. | Es un endpoint administrado por el proveedor, confirmado por separado. |

Confirmá solo lo que el equipo vaya a usar. Una negativa no deja config ni dependencia huérfana.

## Limpiar o volver atrás

El journal queda en:

```text
~/.local/share/pegasus-harness/journal-v3.json
```

El comando `uninstall` borra únicamente entradas creadas por Pegasus cuyo baseline no cambió. Si editaste un artifact, si no hay journal válido o no puede probarse la propiedad, se preserva. Nunca uses rollback para borrar configuración o archivos que ya eran de la cuenta.

## Próximo paso

- Para entender el flujo y los roles: [architecture.md](architecture.md).
- Para el contrato de inclusión y seguridad: [docs/contrato-inclusion-artifacts.md](docs/contrato-inclusion-artifacts.md).
- Para instalación aditiva, migración y aceptación RC: [docs/instalacion-aditiva-v3.md](docs/instalacion-aditiva-v3.md).
