# Instalacion limpia v2

Pegasus Harness v2 se instala desde cero. No reutilice una configuracion existente en la cuenta destino.

## Antes de empezar

- Linux o WSL2.
- Acceso root mediante `sudo`.
- Python 3.12 o superior.
- Una cuenta Linux no root sin `~/.config/opencode` para OpenCode y sin `~/.claude` para Claude Code.
- Archivo de release y checksum obtenidos por un canal autenticado.

## Instalacion

```sh
sha256sum -c pegasus-harness-v2.0.0.tar.gz.sha256
tar -xzf pegasus-harness-v2.0.0.tar.gz
cd pegasus-harness-v2.0.0
sudo ./install.sh --target-user <linux-user> --client all
```

El instalador nunca descarga Pegasus. Instala los binarios requeridos para OpenCode dentro de la cuenta destino y luego valida los assets administrados.

## Si la cuenta ya tiene configuracion

El instalador rechaza directorios existentes para no mezclarlos con v2. Haga una copia manual de lo que necesite conservar, limpie la configuracion de la cuenta o instale en otra cuenta Linux. Recién entonces ejecute el comando de instalacion.

## Operacion

Reinicie OpenCode al terminar: la configuracion se lee al inicio del proceso. Para comprobar una instalacion v2 existente:

```sh
python3 bin/pegasus --target-user <linux-user> --client all validate
```

Para retirar los archivos administrados por v2:

```sh
python3 bin/pegasus --target-user <linux-user> uninstall
```
