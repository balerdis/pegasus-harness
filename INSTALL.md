# Instalar Pegasus

Este es el recorrido corto que probamos con una cuenta Linux limpia. Pegasus se instala en el usuario que ejecuta `./install.sh`; no hace falta usar `sudo` para el apply.

## 1. Elegir la cuenta

Si querés practicar sin tocar tu usuario normal, creá una cuenta separada y entrá en ella:

```sh
sudo useradd -s /bin/bash -m pegasus-release
sudo -iu pegasus-release
```

Si lo vas a instalar en tu cuenta actual, omití esas dos líneas.

## 2. Descargar y aplicar

Usá el tag final que quieras distribuir. El ejemplo usa `v3.1.1`:

```sh
RELEASE_TAG="v3.1.1"
mkdir -p "$HOME/Downloads/pegasus-$RELEASE_TAG"
cd "$HOME/Downloads/pegasus-$RELEASE_TAG"

BASE_URL="https://github.com/balerdis/pegasus-harness/releases/download/$RELEASE_TAG"
ARCHIVE="pegasus-harness-$RELEASE_TAG.tar.gz"

curl -fL -O "$BASE_URL/$ARCHIVE"
curl -fL -O "$BASE_URL/$ARCHIVE.sha256"
curl -fL -O "$BASE_URL/release-manifest.json"

sha256sum -c "$ARCHIVE.sha256"
tar -xzf "$ARCHIVE"
cd "pegasus-harness-$RELEASE_TAG"

curl -fsSL https://opencode.ai/install | bash
source ~/.bashrc

OPENCODE_BIN="$(command -v opencode)"
printf '%s\n' "$OPENCODE_BIN"

./install.sh --client opencode \
  --confirm cbm \
  --confirm engram \
  --decline playwright \
  --confirm context7

cd
opencode
```

El comando de instalación muestra el plan antes de aplicar. Si querés otras integraciones, cambiá solamente las decisiones `--confirm` y `--decline`. Para usar Playwright necesitás tener un navegador instalado por fuera de Pegasus.

Dentro de OpenCode, `/connect` configura el proveedor y `/models` deja elegir el modelo. Pegasus no toca credenciales ni impone modelos.

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
