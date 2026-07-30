# Sergio style example: Alfabeta laboratorios

Use this as style reference, not as reusable facts for every message.

```text
Listo el tema de los laboratorio en Alfabeta. Andres tenias razon en tu deteccion del problema de laboratorios likeados a los medicamentos. Te comento que paso:

el proceso de importacion de albeta que tenemos armado sobre los archivos (de texto plano de columna fija <-- tecnologia arcaica pero bue...), tenia un bug de lectura respecto a la posicion en cada fila del archivo manual_nuevaversion.dat, porque segun la especificacion (la ultima, no se si van cambiando o no, la verdad que ahi no nos enteramos si cambian la estructura) el código de laboratorio estaba en la posición 127, pero el proceso lo estaba leyendo desde la posición 125, eso hacía que se mezclaran campos contiguos: IVA + descuento PAMI + primer dígito del laboratorio.

Ejemplo que nos pasaste:
- FEMEXIN 28 debía quedar asociado a Elea, código 498.
- El sistema lo estaba leyendo como 024, por eso terminaba asociado a Mar.

con la correccion del fix que subi a produccion, se corrigio lo siguiente:
- lectura correcta del código de laboratorio,
- lectura correcta del descuento PAMI,

tambien ahora, el proceso lo modifique para tome la info del archivo laboratorios.txt, porque el manual_nuevaversion.dat solo tenia una descripcion corta del laboratorio y eso quedaba todo mal en la carga de "laboratorios" que teniamos en nuestras tablas.

Para arreglar este tema, tome precauciones:

1.- probé la corrección localmente con una foto productiva actualizada de Leannec, Ospreviene y Osfatun
2.- luego de comprobar que todo este ok en mi local con la foto productiva, hice backup en produccion, y hice la importacion de alfabeta del archivo mensual de abril, ejecute algunas queries para ver que ahora si la medicacion este bien apuntada los laboratorios que corresponde.

resultados :
nuestras tablas de "staging" quedaron asi:
- ab_laboratorios pasó a 797 registros, coincidiendo con laboratorios.txt,
- ab_medicamentos pasó a 53.801 registros del mensual completo,

respecto al laboratorio que informaste (lo tome como caso testigo):
- FEMEXIN/FEMEXIN 28 quedaron en Elea,
- FEMEXIN HIERRO quedó en Elea (inactivo),
```
