# Sergio style example: Alfabeta guardrails version docs

Use this as style reference for repo files such as `README.md`, `changelog.md`, and `mysql.sql`. Keep the facts task-specific; copy the voice, not the exact content.

## README style

```text
# v2.9 · Base de protecciones contra posibles importaciones de Alfabeta con data (archivos planos de columna fija) cambiada a nivel estructura de parseo.

## Resumen

Funcionalidad de proteccion para cortar importaciones de alfabeta cuando los archivos de Alfabeta vengan rotos, incompletos o sospechosos.
La parte importante es que en el pre-chequeo (tecnicamente seria un "preflight") ya deja evidencia en tablas de auditoria antes de vaciar tablas y llegado el caso bloquea la ejecucion del importador hasta que grabe en las tablas que se puede seguir. Tambien da la posibilidad de deshabilitarlo o habilitarlo a voluntad, (deshabilitado por default).

### Objetivo

- separar la persistencia lo que registra el monitor de especificacion (pdf) de alfabeta que deja en las tablas de `ab_spec_monitor_*`;
- permitir obtener un set de archivos de alfabeta "inicial" contra el que comparar las ulteriores veces.
- permitir con la info grabada en las tablas, revisar que paso, donde paso y cuando.
- dejar todo documentado en este README.md

## Componentes

| Componente | Ruta | Propósito |
| --- | --- | --- |
| Migración | `custom/versiones/v2.9/mysql.sql` | Crea tablas para ejecuciones, archivos, busquedas, alertas y reviews. |
| Controller | `custom/api/secciones/api_alfabeta/api_alfabeta_controller.php` | Se fija en los archivo requeridos, corre el pre-chequeo inicial (preflight) y frena antes del truncate cuando el resultado viene del pre-chequeo viene como `blocked` o `error_preflight`. |
| Model | `custom/api/secciones/api_alfabeta/api_alfabeta_model.php` | Persiste las ejecuciones, los archivos analizados, las alertas, y las revisiones grabadas para dejar pasar o no los bloqueos que puedan ocurrir. |

## Comportamiento

- `alfabeta_importar()` utiliza el pre-chequeo (preflight) para evitar hacer truncate de las tablas ab_*, cuando ocurrer bloqueos con codigos como `blocked_preflight` o `error_preflight`
- Cuando ocurren bloqueos o warnings, el importador deja en la salida de su operatorio cosas como `IMPORT_STATUS=blocked_preflight`, `IMPORT_STATUS=error_preflight` o `IMPORT_STATUS=passed_with_warnings`, más `IMPORT_SUMMARY=...`
- El importador tiene seteado internamente que se van a requerir 13 archivos requeridos [...], si alguno falta salta con bloqueo.
- El flujo actual solo permite desbloquear o dejar como buenos los warnings [...], porque los bloqueos de magnitud (cambio la estrutura) bloquean el proceso por completo.

## Deploy en produccion:

1. aplicar `custom/versiones/v2.9/mysql.sql`;
2. desplegar controller + model con la persistencia/validación real;
3. correr `php path_to_document_root/common/includes/thirdparty/vendor/bin/phpunit tests/AlfabetaImportGuardrailsTest.php`;
4. mantener `_ALFABETA_IMPORT_GUARDRAILS_ENABLED` apagado por default hasta terminar calibración y validación de archivos reales;
```

## Changelog style

```text
# Monitor 2 de resguardo ante falla en los archivos de Alfabeta

Este monitor, bloquea el importador si detecta problemas, antes de generar la importacion cuando: falten archivos, vengan mal o el preflight falle de forma inesperada.

### Este desarrollo incluye estas features:

1- una migración `custom/versiones/v2.9/mysql.sql` con la creacion de las tablas `ab_import_guardrail_runs`, `ab_import_guardrail_files`, `ab_import_guardrail_findings`, `ab_import_guardrail_alerts` y `ab_import_guardrail_reviews`.
2- una declaración bootstrap en `custom/api/secciones/api_alfabeta/api_alfabeta_controller.php` con los 13 archivos requeridos; Si el pre-chequeo falla, bloquea la importacion de alfabeta.
3- la data guardada en las tablas, incluye las ejecuciones, los hallazgos, las alertas obtenidas, las reviews, y el resumen de lo encontrado.
4- Importador se aprovecha que el metodo de invocacion es por wget, y devuelve un status code http de 400 (cuando bloquea por error de pre-chequeo 'preflight') o status code http de 500 si algun error con el pre-chequeo ocurriera interno desconocido, y bloquea la ejecucion del importador.
5- Se puede desactivar warnings invocando el endpoint `alfabeta_import_guardrail_aprobar_warning`, no asi los bloqueos.
6- tests en `tests/AlfabetaImportGuardrailsTest.php` para chequea, contrato de archivos, generando bloqueo por `error_preflight` o generando warning.
7- documentación exhaustiva en `custom/versiones/v2.9/README.md` .
8- el cron `crons/updateAlfabeta*.sh` como usa wget se bloquea por que se devuelve status code http de 409 o 500 y deja en el html descargado informacion importante del status de lo que ocurrio
```

## SQL comment style

```sql
-- v2.9 - tablas de auditoria y registro de las ejecuciones del monitor de archivos importados de alfabeta
```

## Voice notes

- Prefer practical names over polished release wording: `Monitor 2`, `proteccion`, `pre-chequeo`, `data`, `bloquea la importacion`.
- It is OK if the Spanish is conversational and not copy-edited to corporate grammar.
- Keep sections direct: `Deploy en produccion`, `cuando hay que revisar, como hacer`, `resultados`, `Recapitulando`, `Rollback de todo esto`, `cosas a revisar`.
- For version docs, the goal is that Sergio can read it later and feel it sounds like something he wrote after doing the work.
- Preserve the user's domain framing: fixed-column flat files can change at parse-structure level; this is the reason the monitor exists.
- Avoid “improving” away Sergio's rough but intentional repo-doc voice. Correct dangerous facts, paths, commands, and states; otherwise keep his expression.
