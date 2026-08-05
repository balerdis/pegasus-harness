# Distribucion de releases

Los releases v2 se preparan desde un tag semantico anotado e inmutable, por ejemplo `v2.0.0`.

1. Ejecute los validadores locales.
2. Cree el tag sobre el commit validado.
3. Genere un archivo fuente nuevo con `build_release_manifest.py`.
4. Publique el archivo, su checksum y el manifest en el release que corresponde al tag.

```sh
python3 tools/build_release_manifest.py --tag v2.0.0 --archive dist/pegasus-harness-v2.0.0.tar.gz --output dist/release-manifest.json
```

La herramienta exige un tag anotado, `install.sh` trackeado como ejecutable y un digest que coincida con el contrato del release. No crea tags ni publica assets. SHA-256 prueba integridad frente al checksum verificado, no la identidad independiente de quien lo publicó.
