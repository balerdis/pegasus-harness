# Distribución de releases (v4)

v4 no tiene tarball ni `install.sh`: cada release publica un wheel (`pegasus-harness`) y un shim `pegasus` de una sola pantalla — los dos assets que [INSTALL.md](../INSTALL.md) e [INSTALL_BY_AGENT.md](../INSTALL_BY_AGENT.md) instruyen descargar y verificar. Pegasus no declara ninguna dependencia, así que no hay lockfile que publicar ni que verificar. No hay pipeline de CI en este repositorio: los pasos siguientes son manuales, corridos por quien prepara el release.

1. Sobre un commit con la suite verde (`PYTHONPATH=src:tests python3 -m unittest discover -s tests -q`), confirmá que `pyproject.toml` declara la versión que vas a publicar y creá el tag anotado `vX.Y.Z` sobre ese commit.
2. Construí el wheel con lo que ya usa cualquier mantenedor: `pip wheel . --no-deps -w dist/`. El nombre resultante, `pegasus_harness-X.Y.Z-py3-none-any.whl`, tiene que declarar la misma versión que `pyproject.toml` en ese commit — `tools/build_release_evidence.py` lo verifica y rechaza el wheel si no coincide.
3. Generá la evidencia del release con `tools/build_release_evidence.py`, apuntando al tag:

   ```sh
   python3 tools/build_release_evidence.py \
     --wheel dist/pegasus_harness-X.Y.Z-py3-none-any.whl \
     --tag vX.Y.Z \
     --output dist/release-manifest.json
   ```

   El script no construye el wheel — lo toma tal cual existe, y sólo certifica el commit, la versión y el hash de cada asset (`release-manifest.json` y un `.sha256` por asset). Sin `--tag`, describe el `HEAD` limpio; con el worktree sucio, se niega.
4. Publicá en GitHub Releases, sobre ese mismo tag, los cinco archivos que `INSTALL.md` descarga: el wheel, `bin/pegasus` (publicado como `pegasus`), sus dos `.sha256`, y `release-manifest.json`. El checksum de cada asset registra solo su basename, nunca una ruta de staging, para que `sha256sum -c` funcione tal como se descargó.
5. El release de GitHub debe ser no-draft y no-prerelease para que el contrato `latest` lo ofrezca. Verificá manualmente, descargando cada asset por su ruta versionada y por `.../releases/latest/download/<asset>`, que ambos coinciden en bytes y en el checksum publicado.

`tools/build_release_manifest.py` sigue existiendo y sigue sin tocarse: reproduce la evidencia de los tags `v3.1.x` que ya se publicaron con tarball, leyendo sus fuentes con `git show <tag>:ruta` para poder seguir respondiendo por esos releases aunque `install.sh` ya no esté en el árbol de trabajo. No tiene rama para el wheel de v4, a propósito — ver el docstring de `tools/build_release_evidence.py`.

Este documento no describe un proceso de aceptación aislada por perfil ni una promoción RC→final automatizada: eso era de v3.1.1, corrido por un dispatch de CI que esta rama no tiene. Si v4 necesita ese nivel de verificación operatoria, es trabajo nuevo, no una adaptación de lo anterior.
