# Distribucion de releases

Los releases de Pegasus son distribuciones de version semantica, no ramas
mutables. La integridad por SHA-256 no equivale a autenticidad independiente:
confirma que el archivo coincide con el checksum que se verifico, pero no
acredita por si sola quien publico ambos archivos.

1. Verifique localmente el commit revisado.
2. Cree sobre ese commit un unico tag anotado e inmutable, por ejemplo `v1.2.3`.
3. Use `build_release_manifest.py` para generar el archivo fuente directamente
   desde ese tag. La herramienta rechaza un archivo existente, exige que
   `install.sh` este trackeado con modo Git `100755` e incluido como `0755`, y
   prueba que coincide byte a byte con el tag y con el digest de
   `baseline-manifest.json` de ese mismo tag.
4. Genere el manifest del release con el tag, SHA del commit, digests del archivo
   y checksum, y los clientes soportados.
5. Suba esos tres assets al GitHub Release que coincide con el tag.

Use `python3 tools/build_release_manifest.py --tag vX.Y.Z --archive <new-archive>
--output <manifest>` despues de crear el tag. El comando rechaza tags livianos,
nombres no semanticos y archivos de salida preexistentes; no crea tags ni publica
assets. El manifest registra el objeto del tag, el commit, el checksum del
archivo y el digest/modo de `install.sh`.

Nunca mueva ni reutilice un tag de release. El repositorio no implementa descarga
remota ni autoactualizacion: requeririan una recuperacion autenticada del release
y una politica de firmas, fuera de esta base local portable. Hoy no hay una
politica de firmas ni una verificacion criptografica de identidad del publicador:
obtenga el checksum por un canal autenticado e independiente, o no lo trate como
prueba de autenticidad. El operador descarga, verifica, extrae y luego ejecuta
`sudo ./install.sh --target-user <linux-user>`; el wrapper nunca descarga Pegasus
ni recomienda curl-pipe-bash.
