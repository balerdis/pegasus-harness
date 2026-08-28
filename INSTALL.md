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

Usá el tag que quieras distribuir. El ejemplo usa `v4.0.0`; reemplazalo por el tag real cuando exista
un release publicado — hoy, mientras se desarrolla 4.0.0, no hay ninguno todavía.

```sh
RELEASE_TAG="v4.0.0"
mkdir -p "$HOME/Downloads/pegasus-$RELEASE_TAG"
cd "$HOME/Downloads/pegasus-$RELEASE_TAG"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"

curl -fL -O "$BASE_URL/pegasus_harness-4.0.0-py3-none-any.whl"
curl -fL -O "$BASE_URL/pegasus_harness-4.0.0-py3-none-any.whl.sha256"
curl -fL -O "$BASE_URL/requirements.txt"
curl -fL -O "$BASE_URL/requirements.txt.sha256"
curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c pegasus_harness-4.0.0-py3-none-any.whl.sha256
sha256sum -c requirements.txt.sha256
sha256sum -c pegasus.sha256
```

Los tres `.sha256` alcanzan para verificar bytes; `release-manifest.json` además ata esos tres
archivos al commit exacto que los produjo (`tag`, `commit`, `package_version`), generado por
`tools/build_release_evidence.py`. Si `sha256sum -c` falla en cualquiera de los tres, no sigas: no
tenés lo que el release publicó.

*Esta sección no se ejecutó en esta verificación: `curl` contra GitHub necesita red, que este entorno
de trabajo tiene prohibida. Lo que sí se probó, con un wheel construido localmente y sus propios
checksums, es que `sha256sum -c` valida exactamente estos tres archivos — ver el reporte de esta
tarea para la corrida real.*

## 3. Instalar el venv privado

Pegasus vive en `$XDG_DATA_HOME/pegasus-harness/` si esa variable apunta a una ruta absoluta, o si no
en `~/.local/share/pegasus-harness/`. Dentro de ese directorio va `venv/`, su venv privado:

```sh
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pegasus-harness"
python3 -m venv "$DATA_DIR/venv"

"$DATA_DIR/venv/bin/python" -m pip install --require-hashes -r requirements.txt
"$DATA_DIR/venv/bin/python" -m pip install --no-deps pegasus_harness-4.0.0-py3-none-any.whl
```

El primer `pip install` necesita red: baja `PyYAML` desde el índice de paquetes y verifica cada
archivo contra los hashes ya fijados en `requirements.txt` antes de instalarlo — si algo no calza,
`pip` se niega. El segundo no la necesita: instala el wheel que ya descargaste y verificaste, sin
volver a resolver nada (`--no-deps`).

*`python3 -m venv "$DATA_DIR/venv"` se ejecutó tal cual y terminó en 0. El primer `pip install
--require-hashes` no se pudo completar sin red: se intentó forzarlo íntegramente offline (venv nuevo,
`--no-index --find-links` contra un directorio local) y no hay wheel de `PyYAML` fijado por hash
disponible en este disco, sólo su código fuente, que a su vez pide `setuptools`, `wheel` y `Cython`
para construirse — encontrar esos tres localmente y sin red no fue posible; el paso queda sin ejecutar
contra el índice real y marcado como tal. El segundo sí se ejecutó, contra el wheel `.dev0` que
construye este checkout (no hay todavía un `4.0.0` publicado), y terminó con
`Successfully installed pegasus-harness-4.0.0.dev0`.*

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

Sin el `--require-hashes` del paso 3 completo, este comando falla al importar `PyYAML` — es la señal
de que falta ese paso, no un problema del lanzador. Con las dependencias instaladas, `doctor` reporta
qué CLIs anfitrionas detecta.

*Se probaron las dos situaciones. Repitiendo exactamente los pasos 3 y 4 de esta guía sin completar el
`pip install --require-hashes` (porque necesita red), `pegasus doctor` invocado a través del shim
falló al importar `yaml`, con el traceback esperado — la falla real que documenta el párrafo de
arriba, no una hipótesis. Con `PyYAML` disponible por otra vía únicamente para esta verificación (no
la del paso 3), `pegasus doctor` corrió de punta a punta a través del shim, del venv privado y del
módulo `pegasus`, con la salida `OpenCode: not found on this machine.` — correcta, porque esa cuenta de
prueba no tenía OpenCode instalado.*

### Sobre `pegasus setup`

`pegasus setup` construye el venv y deja el shim, y sirve **desde un checkout** — por ejemplo
mientras desarrollás. Instalado desde el wheel, como en esta guía, no puede reconstruirse a sí
mismo, y la razón no es un detalle de implementación: para rehacer el venv hacen falta el wheel y
el lockfile con los hashes fijos, y una instalación no guarda ninguno de los dos. No hay de dónde
sacarlos.

Corrido en esa situación, el comando lo dice y no toca nada:

```
setup builds the private venv out of this project's own checkout, and
.../requirements.txt is not there. An installed Pegasus does not keep the wheel or the
lockfile it came from, so it cannot rebuild its own venv: install again from the release,
which is safe to repeat, or run this from a checkout.
```

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
