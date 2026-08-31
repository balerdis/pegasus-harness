# Instalar Pegasus

Pegasus 4 no se instala con un instalador propio: se instala como cualquier paquete de Python, dentro
de un venv privado que sólo Pegasus usa, y después se deja un lanzador (`pegasus`) en el PATH que
arranca ese venv sin que usted tenga que activarlo a mano. Este es el recorrido corto que probamos con
una cuenta Linux limpia. No hace falta `sudo` en ningún paso.

## 1. Elegir la cuenta

Si querés practicar sin tocar tu usuario normal, creá una cuenta separada y entrá en ella:

```sh
sudo useradd -s /bin/bash -m pegasus-release
sudo -iu pegasus-release
```

Si lo vas a instalar en tu cuenta actual, omití esas dos líneas.

## 2. Descargar y verificar

Usá el tag que quieras instalar. El ejemplo usa `v4.1.2`, que es el último publicado.

```sh
RELEASE_TAG="v4.1.2"
mkdir -p "$HOME/Downloads/pegasus-$RELEASE_TAG"
cd "$HOME/Downloads/pegasus-$RELEASE_TAG"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"

curl -fL -O "$BASE_URL/pegasus_harness-4.1.2-py3-none-any.whl"
curl -fL -O "$BASE_URL/pegasus_harness-4.1.2-py3-none-any.whl.sha256"
curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c pegasus_harness-4.1.2-py3-none-any.whl.sha256
sha256sum -c pegasus.sha256
```

Los dos `.sha256` alcanzan para verificar bytes; `release-manifest.json` además ata esos dos
archivos al commit exacto que los produjo (`tag`, `commit`, `package_version`), generado por
`tools/build_release_evidence.py`. Si `sha256sum -c` falla en cualquiera de los dos, no sigas: no
tenés lo que el release publicó.

Esta es la única sección de la instalación que necesita red, y es inevitable: hay que bajar los
bytes que se van a instalar. Pegasus no tiene dependencias de terceros, así que no hay ningún
paso más adelante que necesite volver a salir a internet.

*Esta sección no se ejecutó en esta verificación: `curl` contra GitHub necesita red, que este entorno
de trabajo tiene prohibida. Lo que sí se probó, con un wheel construido localmente y sus propios
checksums, es que `sha256sum -c` valida exactamente estos dos archivos — ver el reporte de esta
tarea para la corrida real.*

## 3. Instalar el venv privado

Pegasus vive en `$XDG_DATA_HOME/pegasus-harness/` si esa variable apunta a una ruta absoluta, o si no
en `~/.local/share/pegasus-harness/`. Dentro de ese directorio va `venv/`, su venv privado:

```sh
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pegasus-harness"
python3 -m venv "$DATA_DIR/venv"

"$DATA_DIR/venv/bin/python" -m pip install --no-deps pegasus_harness-4.1.2-py3-none-any.whl
```

Pegasus no tiene dependencias de terceros, así que hay un solo `pip install`, y no necesita red:
instala el wheel que ya descargaste y verificaste en el paso anterior, sin resolver nada más
(`--no-deps`).

*`python3 -m venv "$DATA_DIR/venv"` se ejecutó tal cual y terminó en 0. El `pip install --no-deps`
también se ejecutó tal cual, sin red, y terminó con `Successfully installed pegasus-harness-4.1.2`.*

## 4. Dejar el lanzador en el PATH

```sh
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
install -m 755 pegasus "$BIN_DIR/pegasus"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "agregá $BIN_DIR a tu PATH (por ejemplo, en ~/.bashrc: export PATH=\"$BIN_DIR:\$PATH\")" ;;
esac
```

`pegasus` es un script `sh` de una sola pantalla: busca ese mismo venv y le pasa el control. No importa
la cuenta ni el shell — es el único archivo que tiene que existir *antes* de que Pegasus mismo pueda
correr.

*Ejecutado tal cual: `install -m 755 pegasus "$BIN_DIR/pegasus"` dejó el shim con permiso `0755` en un
`bin_dir` de prueba, y el chequeo de PATH se probó con las dos ramas del `case` (ausente y presente).*

## 5. Verificar

```sh
pegasus doctor
```

Como Pegasus no tiene dependencias de terceros, no hay nada que quede a medio instalar entre los
pasos 3 y 4: si el `pip install --no-deps` del paso 3 terminó en 0, `doctor` ya puede correr.
Reporta qué CLIs anfitrionas detecta.

*Se probó de punta a punta con un wheel construido localmente, instalado sin red y sin `PyYAML`
presente en el venv (`import yaml` falla ahí a propósito, para confirmar que nada lo necesita):
`pegasus doctor`, invocado a través del shim, corrió completo a través del shim, del venv privado y
del módulo `pegasus`, con la salida `OpenCode: not found on this machine.` — correcta, porque esa
cuenta de prueba no tenía OpenCode instalado.*

### Sobre `pegasus setup`

`pegasus setup` construye el venv y deja el shim, y sirve **desde un checkout** — por ejemplo
mientras desarrollás. Instalado desde el wheel, como en esta guía, no puede reconstruirse a sí
mismo, y la razón no es un detalle de implementación: para rehacer el venv hace falta el propio
checkout (su `pyproject.toml` y su `bin/pegasus`), y una instalación no guarda ninguno de los dos.
No hay de dónde sacarlos.

Corrido en esa situación, el comando lo dice y no toca nada:

```
setup builds the private venv out of this project's own checkout, and
.../pyproject.toml and .../bin/pegasus is not there. It also looked for a copy a
previous `setup` run may have kept beside the venv, at .../setup-sources, and found
none there either. An installed Pegasus that never ran `setup` from a checkout has
nothing to rebuild its own venv from: install again from the release, which is safe
to repeat, or run this from a checkout.
```

*Mensaje real, obtenido corriendo `pegasus setup --json` desde un wheel instalado igual que en esta
guía, sin ningún checkout alrededor.*

Para reconstruir el venv, repetí los pasos 3 y 4: son idempotentes y no rompen nada si el venv ya
existe. Es también lo que dice el shim cuando encuentra su venv borrado.

## Lo que sigue bajo su control

| Tema | Cómo trabaja Pegasus |
| --- | --- |
| OpenCode | Usted instala, actualiza y configura el cliente anfitrión. Pegasus no lo hace por usted. |
| Archivos y claves de configuración existentes | Se detectan y se preservan. Una colisión se informa; no se sobreescribe. |
| MCPs opcionales | `pegasus install --cli opencode --mcp <id>` decide qué servidores se instalan; uno no nombrado no se descarga, configura ni registra. |
| Credenciales, proveedores y modelos | Nunca se distribuyen ni se imponen acá. La persona configura las credenciales del proveedor con `/connect` y selecciona el modelo con `/models`, dentro de OpenCode. |
| Rollback | `pegasus restore` devuelve el estado exacto anterior al último comando; `pegasus uninstall --cli opencode` retira sólo lo que el journal reclama como propio. |

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para la política de ownership y rollback, consultá
[docs/pegasus-v4/arquitectura.md](docs/pegasus-v4/arquitectura.md).

Si un agente te asiste, usá [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) antes de recibir comandos de
instalación. Esa guía no lee ni imprime tu configuración o credenciales de OpenCode.
