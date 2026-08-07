# Distribucion de releases

La promoción v3.1 exige un RC inmutable y su evidencia operatoria antes del tag final.

1. Ejecute los validadores locales y cree el tag anotado `v3.1.0-rc.N` sobre el commit validado.
2. Genere un archive RC nuevo, su checksum y manifest con el CBM curado.
3. Publique esos tres assets para el RC y ejecute los cinco perfiles de aceptación aislada manual.
4. Emita los cinco JSON en un directorio root-controlado fuera de `/home`, legible sin escritura sólo por `serg`, y ejecute el verificador como `serg` con `--output-file` nuevo dentro de un directorio `0700` separado.
5. Solo el `rc-acceptance-aggregate.json` con `status: "PASS"` es entrada para crear `v3.1.0` sobre el mismo commit. El verificador no crea tags ni releases. Un fallo exige otro commit y otro RC, nunca mutar tags.

```sh
python3 tools/build_release_manifest.py --tag v3.1.0-rc.1 --archive dist/pegasus-harness-v3.1.0-rc.1.tar.gz --output dist/release-manifest.json
```

La herramienta acepta únicamente `v3.1.0-rc.N`, exige un tag anotado, `install.sh` trackeado como ejecutable y un contrato `v3.1.0`. El checksum publicado siempre registra sólo el basename del archive (nunca una ruta de staging), para que `sha256sum -c` funcione después de descargar los assets. El CBM curado vive en `dependencies/` dentro del commit del RC; el manifest prueba el digest y membresía del archive, contrato, catálogo y provenance. Antes de crear un RC, ejecute `python3 tools/validate_snapshot.py`: valida el catálogo exacto, excluye artifacts no aprobados y comprueba que cada dependencia tenga fuente fija e integridad. No crea tags ni publica assets.

Después de publicar, el responsable ejecuta los cinco perfiles de la [aceptación aislada](aceptacion-rc-v3.1.md): `cbm`, `engram`, `playwright`, `context7` y `final`. Es una prueba operatoria manual: el orquestador valida archive/checksum/manifest, recrea sólo el usuario dedicado reconocido explícitamente y no forma parte de tests ni del pipeline de release. El verificador de matriz es una comprobación Python offline: requiere exactamente esas cinco evidencias `PASS` con la misma identidad RC y escribe una única prueba agregada antes de la promoción.

## Promoción RC final v3.1.1

El commit que contendrá el release final (incluidos los cambios posteriores a RC26) primero recibe el tag anotado e inmutable `v3.1.1-rc.1`. El dispatch con `release_stage: rc` genera y publica sus tres assets y luego se ejecutan los cinco perfiles aislados para ese RC. La promoción final recibe manualmente su evidencia agregada aceptada mediante `accepted_v311_rc1_aggregate_b64`; el dispatch con `release_stage: final` descarga los tres assets publicados de `v3.1.1-rc.1` y rechaza el agregado si no es `PASS`, no contiene exactamente los cinco perfiles o no coincide byte a byte con esa identidad RC. Esa validación termina antes de crear el tag final o construir/subir assets finales. Sólo después crea el tag anotado e inmutable `v3.1.1` sobre el commit de `v3.1.1-rc.1`, vuelve a comparar ambos commits y no sustituye la aceptación aislada. La evidencia de RC26 no puede sustituir la aceptación de `v3.1.1-rc.1`. Desde el tag final genera exactamente estos assets:

- `pegasus-harness-v3.1.1.tar.gz`;
- `pegasus-harness-v3.1.1.tar.gz.sha256`;
- `release-manifest.json`.

El manifest final registra `release_kind: final`, `promotion_rc_tag: v3.1.1-rc.1`, tag object, commit, digest del archive, installer y evidencia de `README.md`, `INSTALL.md`, `INSTALL_BY_AGENT.md`, `MANUAL.md` y esta guía. El release de GitHub debe ser no-draft y `prerelease: false`; sólo así GitHub puede ofrecer el contrato `latest`.

El smoke manual de `v3.1.1-rc.1` usa exclusivamente los tres assets versionados de ese RC. La preflight acepta el RC sólo si el tag, archive, checksum, manifest, raíz y evidencia del archive son el mismo conjunto inmutable. Ese smoke no habilita `latest` ni sustituye la distribución final. La instalación/distribución final usa sólo `v3.1.1`; las rutas versionada y `latest` deben conservar bytes, checksum y manifest idénticos.

Después de publicar, descargá cada asset por sus dos rutas y compará bytes antes de reportar distribución lista. No ejecutes esta verificación desde tests ni como parte de la aceptación:

```text
https://github.com/balerdis/pegasus-harness/releases/download/v3.1.1/<asset>
https://github.com/balerdis/pegasus-harness/releases/latest/download/<asset>
```

Cada par debe conservar basename y SHA-256; el checksum y manifest deben identificar `v3.1.1`, y `latest` no puede resolver a RC, asset incompleto ni bytes regenerados. Si la publicación final es incorrecta, retirá el release y publicá un patch nuevo e inmutable: nunca se mutan tag ni assets ya publicados.
