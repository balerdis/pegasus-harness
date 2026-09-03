# Distribución de releases (v5)

v5 publica un solo archivo: `pegasus`, un `zipapp` de la biblioteca estándar con shebang, construido
por `tools/build_zipapp.py` a partir de `src/pegasus/`. Es el archivo entero que la persona instala —
el asset que [INSTALL.md](../INSTALL.md) e [INSTALL_BY_AGENT.md](../INSTALL_BY_AGENT.md) instruyen
descargar y verificar. No hay wheel, no hay venv, no hay shim aparte: Pegasus no declara ninguna
dependencia y lee su contenido desde adentro del propio zip, así que no queda nada más que empaquetar.
No hay pipeline de CI en este repositorio: los pasos siguientes son manuales, corridos por quien
prepara el release.

1. Sobre un commit con la suite verde (`PYTHONPATH=src:tests python3 -m unittest discover -s tests -q`), confirmá que `pyproject.toml` declara la versión que vas a publicar y creá el tag anotado `vX.Y.Z` sobre ese commit.
2. Construí el artefacto:

   ```sh
   python3 tools/build_zipapp.py --out dist/pegasus
   ```

   Deja `dist/pegasus` (ejecutable, con shebang) y `dist/pegasus.sha256` al lado.
3. Generá la evidencia del release con `tools/build_release_evidence.py`, apuntando al tag:

   ```sh
   python3 tools/build_release_evidence.py \
     --artifact dist/pegasus \
     --tag vX.Y.Z \
     --output dist/release-manifest.json
   ```

   El script no construye el artefacto — lo toma tal cual existe, lo corre (`pegasus doctor --json`)
   para confirmar que el `pegasus_version` que reporta coincide con `pyproject.toml` en ese commit, y
   sólo entonces certifica el commit y el hash (`release-manifest.json` y un `.sha256`). Sin `--tag`,
   describe el `HEAD` limpio; con el worktree sucio, se niega.
4. Publicá en GitHub Releases, sobre ese mismo tag, los cuatro archivos que `INSTALL.md` nombra:
   `pegasus`, su `.sha256`, `release-manifest.json`, y `install.sh` (el archivo en la raíz del
   repositorio, tal cual está en ese commit — no se genera, se sube directo). `install.sh` tiene que
   publicarse en este mismo release, y no en ningún otro lugar (por ejemplo, servido crudo desde
   `raw.githubusercontent.com`): todo lo que instala vive detrás de
   `releases/latest/download/`, así que si el script viviera en una URL aparte podría quedar
   apuntando a un binario de un release distinto del que lo acompaña, exactamente el tipo de
   desincronización que este esquema existe para evitar. El checksum de `pegasus` registra sólo el
   basename, nunca una ruta de staging, para que `sha256sum -c` funcione tal como se descargó.
5. El release de GitHub debe ser no-draft y no-prerelease para que el contrato `latest` lo ofrezca.
   Verificá manualmente, descargando cada uno de los cuatro assets por su ruta versionada y por
   `.../releases/latest/download/<asset>`, que ambos coinciden en bytes (y, para `pegasus`, también en
   el checksum publicado).

`tools/build_release_manifest.py` sigue existiendo y sigue sin tocarse: reproduce la evidencia de los
tags `v3.1.x` que ya se publicaron con tarball, leyendo sus fuentes con `git show <tag>:ruta` para
poder seguir respondiendo por esos releases aunque `install.sh` ya no esté en el árbol de trabajo.
`tools/build_release_evidence.py` tampoco entiende esa forma ni la de v4 (wheel + shim) a propósito —
ver su docstring.

Este documento no describe un proceso de aceptación aislada por perfil ni una promoción RC→final
automatizada: eso era de v3.1.1, corrido por un dispatch de CI que esta rama no tiene. Si v5 necesita
ese nivel de verificación operatoria, es trabajo nuevo, no una adaptación de lo anterior.
