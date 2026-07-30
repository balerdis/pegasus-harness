# Sergio style examples: Alfabeta spec monitor

Use these as style references, not as reusable facts for every message.

## Internal team example

```text
@all , les comento que ya quedó en producción el monitor que chequea el pdf de especificación desde Alfabeta.
Como hablamos hoy, esto viene por el problema que vimos con los archivos de Alfabeta, que son texto plano de columna fija. Si ellos cambian la estructura y no nos enteramos a tiempo, el proceso puede seguir funcionando pero leyendo cualquier cosa.

Lo que quedó armado ahora es un monitor diario que:
1.- entra al portal de Alfabeta con las credenciales configuradas
2.- descarga el PDF de especificación
3.- guarda una copia del PDF
4.- calcula hash del archivo PDF
5.- extrae el texto con la libreria php de pdftotext
6.- calcula hash del texto extraido y normalizado
7.- compara contra el pdf que tenemos como actual y ok, que lo doy por llamar "baseline"
8.- si detecta diferencia, manda mail a Fer, Manuel y yo

El cron quedó corriendo todos los días a las 07:15.
La baseline inicial ya quedó cargada y probada en producción. Las últimas corridas dieron "no_change" como estado.

Si se activa una alarma, NO hay que ignorarla. La idea es que el mail se envie hasta que alguien la desactive o la revise.

Para desactivar una alarma hay dos caminos:
1.- si fue falso positivo:
revisar que el PDF no cambió nada importante de la estructura
marcar la alerta como false_positive
dejar escrito el motivo

2.- si el cambio es válido y lo aceptamos:
revisar que el parser sigue siendo compatible, o hacer el ajuste que corresponda
aprobar una nueva baseline
desde ese momento las próximas corridas comparan contra esa nueva versión

(para manuel y gian) Las tablas que guardan todo esto son:
ab_spec_monitor_runs
ab_spec_monitor_baselines
ab_spec_monitor_alerts
ab_spec_monitor_reviews
ab_spec_monitor_notifications

todo esto en la db de leannec

Por ahora queda funcionando como primera capa de aviso y monitoreo, esto no bloquea importaciones ni toca el proceso de carga normal de alfabeta.
```

## Client example

```text
Andres, como estas?, te comento que ya dejé implementado en producción un primer monitor para el tema de Alfabeta.

Esto lo armé a partir de lo que vimos con el problema de laboratorios. Como Alfabeta trabaja con archivos de texto plano de columna fija, si ellos cambian la estructura y no nos enteramos a tiempo, el proceso puede seguir corriendo pero interpretar mal los datos.

Lo que hace este monitor es entrar todos los días al portal de Alfabeta, descargar el PDF donde ellos publican la especificación de los archivos, y compararlo contra una versión que dejamos aprobada que la doy por llamar "baseline".

Si detecta algun cambio, nos manda un aviso al equipo técnico para revisar si Alfabeta cambió algo en la estructura antes de que eso impacte en una importación.

Ya quedó probado en producción:
descarga el PDF correctamente,
extrae el texto correctamente,
compara contra la baseline,
y las últimas pruebas dieron sin cambios.

Esto no modifica el importador ni bloquea procesos todavía. Es una primera capa de alerta para que no dependamos solamente de que llegue o que se nos reenvíe un mail de aviso.

Mi idea ahora, como segunda etapa, es armar otro control más cerca del importador: validar los archivos reales que llegan de Alfabeta antes de procesarlos, para detectar inconsistencias raras en columnas/campos.
```
