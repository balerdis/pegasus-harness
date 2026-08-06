# Distribucion de releases

La promoción v3.1 exige un RC inmutable y su evidencia operatoria antes del tag final.

1. Ejecute los validadores locales y cree el tag anotado `v3.1.0-rc.N` sobre el commit validado.
2. Genere un archive RC nuevo, su checksum y manifest con el CBM curado.
3. Publique esos tres assets para el RC y ejecute la aceptación aislada manual.
4. Revise el JSON de evidencia; solo entonces cree `v3.1.0` sobre el mismo commit. Un fallo exige otro commit y otro RC, nunca mutar tags.

```sh
python3 tools/build_release_manifest.py --tag v3.1.0-rc.1 --archive dist/pegasus-harness-v3.1.0-rc.1.tar.gz --output dist/release-manifest.json
```

La herramienta acepta únicamente `v3.1.0-rc.N`, exige un tag anotado, `install.sh` trackeado como ejecutable y un contrato `v3.1.0`. El CBM curado vive en `dependencies/` dentro del commit del RC; el manifest prueba el digest y membresía del archive, contrato, catálogo y provenance. Antes de crear un RC, ejecute `python3 tools/validate_snapshot.py`: valida el catálogo exacto, excluye artifacts no aprobados y comprueba que cada dependencia tenga fuente fija e integridad. No crea tags ni publica assets.

Después de publicar, el responsable ejecuta la [aceptación aislada](instalacion-aditiva-v3.md#aceptación-aislada-de-mantenimiento) sobre la cuenta limpia existente `pegasus-harness`. Es una prueba operatoria manual: no forma parte de tests ni del pipeline de release.
