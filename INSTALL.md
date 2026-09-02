# Instalar Pegasus

Pegasus 5 es un solo archivo: `pegasus`. No hay wheel, no hay venv privado, no hay `pip install` — se
descarga, se verifica su checksum, se lo deja ejecutable en el PATH, y listo. Este es el recorrido
corto que probamos con una cuenta Linux limpia. No hace falta `sudo` en ningún paso.

## 1. Elegir la cuenta

Si querés practicar sin tocar tu usuario normal, creá una cuenta separada y entrá en ella:

```sh
sudo useradd -s /bin/bash -m pegasus-release
sudo -iu pegasus-release
```

Si lo vas a instalar en tu cuenta actual, omití esas dos líneas.

## 2. Descargar y verificar

Usá el tag que quieras instalar. El ejemplo usa `v5.0.0`; sustituilo por el último publicado.

```sh
RELEASE_TAG="v5.0.0"
mkdir -p "$HOME/Downloads/pegasus-$RELEASE_TAG"
cd "$HOME/Downloads/pegasus-$RELEASE_TAG"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"

curl -fL -O "$BASE_URL/pegasus"
curl -fL -O "$BASE_URL/pegasus.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c pegasus.sha256
```

`pegasus.sha256` alcanza para verificar los bytes; `release-manifest.json` además ata ese archivo al
commit exacto que lo produjo (`tag`, `commit`, `package_version`), generado por
`tools/build_release_evidence.py`. Si `sha256sum -c` falla, no sigas: no tenés lo que el release
publicó.

Esta es la única sección de la instalación que necesita red, y es inevitable: hay que bajar los bytes
que se van a instalar. Pegasus no tiene dependencias de terceros, así que no hay ningún paso más
adelante que necesite volver a salir a internet.

*Esta sección no se ejecutó en esta verificación: `curl` contra GitHub necesita red, que este entorno
de trabajo tiene prohibida. Lo que sí se probó, con un artefacto construido localmente
(`tools/build_zipapp.py`) y su propio checksum, es que `sha256sum -c` valida el archivo correcto y
rechaza uno alterado — corrida real:*

```
$ sha256sum -c pegasus.sha256
pegasus: OK
```

*y, contra una copia con un byte agregado a mano:*

```
$ sha256sum -c pegasus.sha256
pegasus: FAILED
sha256sum: WARNING: 1 computed checksum did NOT match
```

## 3. Dejar el ejecutable en el PATH

```sh
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
install -m 755 pegasus "$BIN_DIR/pegasus"

case ":$PATH:" in
  *":$BIN_DIR:"*)
    echo "listo: $BIN_DIR ya está en tu PATH" ;;
  *)
    echo "$BIN_DIR todavía no está en tu PATH."
    echo "Para usarlo ahora mismo, en esta terminal:   export PATH=\"$BIN_DIR:\$PATH\""
    echo "Para que quede: cerrá la sesión y volvé a entrar. La mayoría de los sistemas"
    echo "agregan ese directorio al iniciar sesión, pero sólo si ya existía — y lo acabás"
    echo "de crear. Editá tu shell sólo si después de volver a entrar sigue sin aparecer."
    ;;
esac
```

`pegasus` es el único archivo que hace falta: no busca un venv y no depende de nada instalado antes
que él. Es el mismo archivo en Linux y en macOS, y los pasos de arriba son los mismos en los dos.

En Windows el archivo sirve igual, pero este recorrido no: `sha256sum` e `install` no vienen con el
sistema, y Windows no honra el shebang de un archivo suelto, así que ahí se invoca con el lanzador de
Python (`py pegasus`). No lo probamos todavía, y por eso no lo documentamos como si lo hubiéramos
hecho.

**Un `source ~/.bashrc` no alcanza**, y es el error fácil de cometer: quien agrega `~/.local/bin` al
PATH suele ser `~/.profile`, que corre al *iniciar sesión* y no al abrir una terminal. Si volvés a
entrar y `pegasus` sigue sin aparecer, ahí sí editá tu shell.

*Ejecutado tal cual: `install -m 755 pegasus "$BIN_DIR/pegasus"` dejó el archivo con permiso `0755` en
un `bin_dir` de prueba, y el chequeo de PATH se probó con las dos ramas del `case` (ausente y
presente) — corrida real, rama ausente:*

```
$ BIN_DIR=/tmp/.../home/.local/bin; case ":$PATH:" in *":$BIN_DIR:"*) echo presente;; *) echo "$BIN_DIR todavía no está en tu PATH.";; esac
/tmp/.../home/.local/bin todavía no está en tu PATH.
```

### Si venís de una instalación 4.x

Pegasus 4.x dejaba un shim en `~/.local/bin/pegasus` que arrancaba un venv privado propio, en
`~/.local/share/pegasus-harness/venv` (o `$XDG_DATA_HOME/pegasus-harness/venv` si esa variable
estaba definida). El paso 3 de arriba pisa ese shim con el archivo único de 5.0.0 — eso ya está
comprobado y es lo esperado. Lo que el paso 3 no toca es ese venv viejo: queda en disco, sin nada
que lo use.

Ese directorio es distinto del que guarda el journal y los snapshots (`~/.local/share/pegasus-harness/`
sin el `venv` al final), así que borrarlo no toca tu historial de instalación ni tu capacidad de
hacer `pegasus restore`. Para recuperar el espacio:

```sh
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/pegasus-harness/venv"
```

### Si sólo hay `python` (no `python3`) en el PATH

`pegasus` arranca con `#!/usr/bin/env python3`, así que si tu sistema sólo tiene `python` en el PATH
vas a ver:

```
/usr/bin/env: 'python3': No such file or directory
```

con código de salida 127. No es que el archivo esté roto: `env` no encuentra un intérprete llamado
exactamente `python3`. Si ese `python` es Python 3 (comprobalo con `python --version`), corré el
archivo pasándoselo como argumento en vez de ejecutarlo directo — probado acá, funciona igual:

```sh
python "$BIN_DIR/pegasus" doctor
```

## 4. Verificar

```sh
pegasus doctor
```

No hay paso 3 a medias que arreglar: si `sha256sum -c` y el `install -m 755` de arriba terminaron en
0, `pegasus` ya está completo. `doctor` reporta qué CLIs anfitrionas detecta.

*Corrida real, `pegasus` puesto en un `bin_dir` de prueba y llamado por PATH desde otro directorio:*

```
$ pegasus doctor
OpenCode: present at /home/.config/opencode, Pegasus not installed.
```

## Lo que sigue bajo su control

| Tema | Cómo trabaja Pegasus |
| --- | --- |
| OpenCode | Usted instala, actualiza y configura el cliente anfitrión. Pegasus no lo hace por usted. |
| Archivos y claves de configuración existentes | Se detectan y se preservan. Una colisión se informa; no se sobreescribe. |
| MCPs opcionales | `pegasus install --cli opencode --mcp <id>` decide qué servidores se instalan; uno no nombrado no se descarga, configura ni registra. |
| Credenciales, proveedores y modelos | Nunca se distribuyen ni se imponen acá. La persona configura las credenciales del proveedor con `/connect` y selecciona el modelo con `/models`, dentro de OpenCode. |
| Rollback | `pegasus restore` devuelve el estado exacto anterior al último comando; `pegasus uninstall --cli opencode` retira sólo lo que el journal reclama como propio. |

Para el uso diario, seguí [MANUAL.md](MANUAL.md). Para la política de ownership y rollback, consultá
[docs/arquitectura/arquitectura.md](docs/arquitectura/arquitectura.md).

Si un agente te asiste, usá [INSTALL_BY_AGENT.md](INSTALL_BY_AGENT.md) antes de recibir comandos de
instalación. Esa guía no lee ni imprime tu configuración o credenciales de OpenCode.
