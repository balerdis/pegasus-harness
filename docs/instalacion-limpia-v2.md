# Instalacion limpia v2.0.1

Pegasus Harness v2 se instala desde cero. No reutilice una configuracion existente en la cuenta destino.

## Antes de empezar

- Linux o WSL2.
- Acceso root mediante `sudo`.
- Python 3.12 o superior.
- Una cuenta Linux no root sin `~/.config/opencode` para OpenCode y sin `~/.claude` para Claude Code.
- Archivo de release y checksum obtenidos por un canal autenticado.
- Para OpenCode: `~/.opencode/bin/opencode` o `~/.local/bin/opencode` ejecutable, y `~/.local/bin/codebase-memory-mcp` ejecutable. Ambos deben responder a `--version` y `--help`.

## Instalacion

```sh
sha256sum -c pegasus-harness-v2.0.1.tar.gz.sha256
tar -xzf pegasus-harness-v2.0.1.tar.gz
cd pegasus-harness-v2.0.1
sudo ./install.sh --target-user <linux-user> --client all
```

Pegasus no descarga ni instala OpenCode, CBM ni otra dependencia. Solo descubre esos ejecutables dentro del home de la cuenta destino, ejecuta las sondas no mutantes `--version` y `--help`, y recién entonces materializa sus propios assets. Root no aporta su `PATH`: el wrapper entra a la cuenta destino con `sudo -u <linux-user> -H`.

Si alguna sonda falla, falta un binario, la cuenta no es válida o el directorio de cliente ya existe, el proceso se corta con error. Prepare o actualice OpenCode y CBM fuera de Pegasus y vuelva a ejecutar el comando.

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
