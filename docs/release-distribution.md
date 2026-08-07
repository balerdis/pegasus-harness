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
