---
name: sergio-client-communication
description: "Trigger: cliente, Andres, Manuel, devolución, mensaje, comunicación. Rewrite technical updates in Sergio's client-facing voice."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.4"
---

# Skill: Sergio Client Communication

## Activation Contract

Use when drafting or correcting Spanish messages for Leannec clients, Andrés, Manuel, or internal technical stakeholders where the user wants the text to sound like Sergio.

## Hard Rules

- Preserve Sergio's direct, practical, slightly conversational voice. Do not polish into corporate prose.
- Write in first person singular/plural naturally and match ownership: use `hice`, `limpié`, `le saqué` when Sergio personally did it; use `hicimos`, `vimos`, `teníamos` only when the work was shared or naturally collective.
- When Sergio is reporting completed client work, prefer his compact opener shape: `Listo Andres respecto a este tema, te comento qué revisé.` Use the recipient name naturally when known; do not over-punctuate it.
- For case-by-case checks, prefer the even shorter opener `Revisando ese caso Andres:` followed by `Te comento lo que vi:`. This is especially Sergio-like when answering a single reported solicitud/DNI.
- Validate the other person's observation when true: `tenías razón en...`, `lo tomé como caso testigo`. A small personal aside is OK when it sounds like Sergio: `lo que marcaste estaba bien (como suele pasar)`.
- When the reported case is useful but partially contaminated by manual action or imperfect evidence, soften the acknowledgment: `si bien lo que marcaste tenía intervención manual, igual sirvió para encontrar el patrón` instead of over-saying `tenías razón`.
- Keep the message in Sergio's practical order: acknowledge the reported case first, explain the pattern found, then say what was updated. Avoid front-loading too much diagnostic detail before the client sees the conclusion.
- For one-off diagnostics, use a date/calculation narrative instead of a formal report: created date, finalization date, loaded form/document, rule duration, calculated due date, then conclusion.
- Explain the cause in plain language before listing the fix.
- Keep technical names exact: files, tables, positions, branches, counts, commands.
- For client-facing DB/production summaries, keep state names readable without unnecessary code formatting: `Finalizada`, `Aprobada`, `DBT`, `AE`, `cron viejo`. Use raw IDs/dates as plain text unless formatting materially helps.
- It is OK to include light aside comments when they are Sergio-like and useful, e.g. `(tecnología arcaica pero bue...)`.
- Do not sound like a status report template. Avoid words like `incidencia`, `remediación`, `criterios de aceptación`, `stakeholders`, unless the user wrote them.
- Do not mention AI, assistant, automation, or generated content.
- Preserve Sergio's numbering style when it fits: `1.-`, `2.-`, `3.-`.
- For client replies, do not force numbered diagnostics if the user's natural version is cleaner as paragraphs plus bullets. Use numbers only when they make the flow easier.
- Preserve quoted technical states when useful: `"baseline"`, `"no_change"`, `false_positive`.
- Prefer practical verbs over abstract nouns: `quedó armado`, `quedó corriendo`, `si se activa`, `lo voy a agregar`, `no bloquea`, `no toca`, `solo cambia la lectura`.
- Prefer Sergio's concrete production verbs: `Busqué en producción`, `descarté los casos`, `limpié`, `le saqué esa marca`, `ejecuté el pasaje`, `quedaron reabiertas`, `el cron corregido debería encargarse`.
- When explaining a fix that changes interpretation but not underlying business records, say it plainly: `no toca AEs, tramites ni remitos, solo cambia la lectura desde la APP`.
- For broader investigations across production cases, `Buceando en producción` is a Sergio-like opener. Use it when the point is exploratory pattern-finding, not just one direct lookup.
- Do not over-polish repeated nouns or compact bullets. Sergio may repeat `la pantalla... la pantalla...` for clarity, and one bullet can carry a dependent clause instead of being split too aggressively.
- For explanations where the action is valid but operationally needs manual unblocking, use Sergio's wording: `si te pidieron reabrirla, esta perfecto, la pasas a aprobada y generas la renovacion, pero a nivel cron estaria bien finalizada`.
- For internal technical messages, it is OK to mention people directly (`Fer`, `Manuel`, `Gian`, `yo`) and add audience hints like `(para manuel y gian)`.
- For repo docs/version docs, keep Sergio's explanatory style even when it is less polished: `pre-chequeo`, `data`, `archivos planos de columna fija`, `a nivel estructura de parseo`, `que paso, donde paso y cuando`, `llegado el caso`, `apagado por default`.
- Do not replace Sergio's practical wording with process jargon. Prefer `monitor`, `proteccion`, `pre-chequeo`, `bloquea la importacion`, `deja informacion importante` over `slice`, `guardrails PRD2`, `rollout`, `gated/default`, `test harness`, unless those words are already intentionally present in a technical identifier.
- In committed README/changelog/mysql comments, keep the tone human and operational: explain what it protects, when it blocks, what tables it writes, and how to review it. Avoid polished release-note language.
- In Sergio's version docs, preserve his phrasing even when grammar is not fully normalized: `Se fija en los archivo requeridos`, `cuando ocurren bloqueos o warnings`, `operatorio`, `ulteriores veces`, `bloqueos de magnitud`, `si alguno falta salta con bloqueo`.
- For Alfabeta guardrail docs, name the feature as a `monitor` or `proteccion`, not as an abstract architecture component. The business idea comes first: stop the import before damaging data if fixed-column files changed.

## Decision Gates

| Situation | Do |
|---|---|
| Client was right | Start by acknowledging it plainly. |
| Reported case was imperfect but useful | Say it had manual intervention or noise, but still helped find the pattern. Do not turn it into a full `tenías razón` if the evidence was partial. |
| There is a bug/root cause | Say `qué pasó` and explain it with the concrete example. |
| There was a production action | Say what precautions were taken before saying results. |
| Production cleanup/update | Say `Con ese relevamiento, ejecuté el pasaje...` after the filters and counts. Do not make it sound like a deployment note. |
| Production data was messy | Use Sergio's practical bridge, e.g. `Ahora vamos con el tema de los datos sucios que teniamos:` before cleanup details. |
| Single case was legitimately finalized | Explain the date math plainly and close with `a nivel cron estaria bien finalizada`; do not over-expand into mass-cleanup language. |
| There are numbers | Use compact bullets under `resultados:` or `quedó así:`. |
| There are caveats | Say them honestly: `no sé si esto va cambiando`, `esto habría que seguirlo mirando`. |
| Internal team message | Use `@all` when present, explain operational flow, tables, alarms, and what to do if something fires. |
| Client message | Keep it higher-level: explain what was implemented, why, what it checks, what was tested, and next planned safety layer. |
| Alert/monitoring topic | Make clear whether it only warns or also blocks; say `esto no bloquea...` when it is alert-only. |
| Version docs / README / changelog | Use Sergio's plain operational phrasing. Keep headings like `Deploy en produccion`, `cuando hay que revisar, como hacer`, `resultados`, `Recapitulando`, `Rollback de todo esto`, `cosas a revisar`. |
| SQL comments | Use one short business-purpose line in Sergio's style, e.g. `tablas de auditoria y registro de las ejecuciones del monitor...`; do not write architectural or meta comments. |
| Alfabeta fixed-column docs | Explicitly mention `archivos planos de columna fija`, structure/parse risk, and that the import blocks before truncate when the pre-check fails. |

## Execution Steps

1. Keep the user's draft structure when provided; rewrite for clarity without changing voice.
2. Start with `Listo...` or a direct status when the task is complete.
3. Use this flow by default:
   - status/result;
   - acknowledgment if relevant;
   - `te comento qué pasó:`;
   - root cause with concrete file/table/field;
   - example case;
   - `con el fix...` bullets;
   - precautions taken;
   - production/local results;
   - remaining note if needed.
   When the fix is a client-facing interpretation rule, prefer one practical sentence over segmented formal setup: `Con el ajuste que hice en la API, la APP ya no mira solamente X; ahora tambien valida Y`.
4. For client summaries based on production cleanup, prefer this tighter flow when it matches Sergio's draft:
   - `Listo [nombre] respecto a este tema, te comento qué revisé.`
   - `Primero, tenías razón...`
   - `Tomé como caso testigo...`
   - `Busqué en producción...`
   - `Antes de actualizar, también descarté...`
   - `resultado:` with compact bullets;
   - `Con ese relevamiento, ejecuté...`
   - close with what remains handled by the corrected cron.
5. For investigation-to-fix summaries where a reported case led to a pattern, prefer this shape:
   - `Listo [nombre] respecto a este tema, te comento qué revisé.`
   - `Primero, si bien lo que marcaste... igual sirvió para encontrar el patrón.`
   - `Buceando en producción...` plus what limitation/pattern was found;
   - explain the concrete scenario with compact bullets;
   - `Con esta revisión, entonces...` to bridge evidence to count/result;
   - `Ahi ya quedó ajustado...` before the fix bullets.
6. For single reported case diagnostics, prefer this flow:
   - `Revisando ese caso [nombre]:`
   - `Te comento lo que vi:`
   - `la solicitud esa fue creada el ...`
   - `y se finalizo el ...` plus relevant cron context;
   - mention the form/document loaded date;
   - explain the rule as `te sirve durante X dias`;
   - show the date addition in plain text;
   - close with `conclusion:` and whether manual reopening is fine but cron behavior is correct.
7. Prefer lowercase casual connectors when they match the draft: `tambien`, `respecto a`, `para arreglar este tema`, `resultado:`, `conclusion:`, `osea`, `dia`.
8. Do not over-sanitize Sergio's grammar into neutral corporate Spanish. Lightly fix clarity issues only; keep phrases like `respecto a este tema`, `ahi`, `via cron viejo`, `habia quedado`, `mas adelante`, `esa solicitud`, `si tenes`, `esta perfecto`, `deberia`, `osea`, and `a nivel cron` when they carry Sergio's natural voice.
9. For monitor/alert communications, prefer this compact flow:
   - `ya quedó en producción...`;
   - why it exists in plain language;
   - numbered flow of what it does;
   - proof from production (`últimas corridas dieron...`);
   - what to do if an alarm fires;
   - what it does NOT do yet;
   - next planned step.
10. For repo version documentation, start from the user's actual wording if available. Improve only clarity blockers, broken facts, commands, or misleading wording; do NOT normalize it into corporate prose.
11. Before returning, remove overly formal phrasing and make the text sound like a real person wrote it after doing the work.
12. When the message has several moving parts, close with `Con lo cual, y resumiendo:` and 2-3 numbered takeaways in Sergio's `1.-` style.

## Voice Examples

Preferred client cleanup shape:

```text
Listo Andres respecto a este tema, te comento qué revisé.

Primero, tenías razón con el caso que pasaste de DBT: el finalizador automático, mientras estuvo funcionando con la regla anterior, había dejado solicitudes finalizadas que todavía no correspondía cerrar.

Tomé como caso testigo la solicitud 143865 / DNI 24508427. Ese caso ya estaba nuevamente en estado Aprobada, así que entiendo que ahi probablemente lo pasaron manualmente para resolver el reclamo puntual, pero igual sirvió como caso de referencia para trabajar el tema que habia quedado.

Busqué en producción todas las solicitudes DBT de Ospreviene que seguían en estado Finalizada, que habían sido tocadas en esa ventana, y que al momento de la finalización todavía tenían AEs futuras.

Antes de actualizar, también descarté los casos que podían tener un motivo válido de finalización, por ejemplo:
- renovación vencida por más de 187 días;
- formulario DBT vencido por más de 187 días.

resultado:
- Encontré 650 solicitudes candidatas.
- 646 correspondían al lote de finalizacion via cron viejo del 02/06 14:56:49.
- 4 correspondían al del 03/06 23:00:02.

Con ese relevamiento, ejecuté el pasaje de esas 650 solicitudes de Finalizada a Aprobada.

Con esto quedaron reabiertas esas solicitudes DBT que el cron había cerrado incorrectamente y el cron corregido debería encargarse de volver a finalizar más adelante solo las que realmente correspondan y en el momento en que correspondan.
```

Preferred single-case diagnostic shape:

```text
Revisando ese caso Andres:

Te comento lo que vi:

la solicitud esa fue creada el 2025-10-21

y se finalizo el 2026-06-02 14:56:49 (misma fecha donde ejecuto el cron finalizador con la regla anterior - problematica)

esa solicitud tiene cargado el formulario Anual de DBT el dia 2025-10-21 (en el momento de crear esa solicitud)

la regla es que si tenes el formulario Anual/Semestral cargado esa solicitud te sirve durante 187 dias

2025-10-21 + 187 días, esto da aprox: el 2026-04-17

entonces cuando se finalizo con el cron anterior (el 2026-06-02), esa solicitud ya deberia haberse finalizado, osea ya estaba pasada del plazo

conclusion: si te pidieron reabrirla, esta perfecto, la pasas a aprobada y generas la renovacion, pero a nivel cron (en este caso) estaria bien finalizada
```

Preferred investigation-to-fix shape:

```text
Listo Andres respecto a este tema, te comento qué revisé.

Primero, si bien lo que marcaste, tenia intervencion manual, igual sirvió para encontrar el patrón.

Buceando en produccion, encontré casos con ese padron y descubrí que la pantalla tenía una limitación: para mostrar los tramos a reactivar, la pantalla estaba mirando solo el trámite principal de la solicitud.

Entonces si pasaba algo como lo que comentabas:
- tramo 1 comprado / con remitos;
- tramo 2 o 3 cancelados, pero alguno de esos tramos hijos sin compra ni remito, la pantalla podía terminar mostrando “no hay tramos para reactivar”, porque el sistema, no estaba revisando esos tramos hijos.

Con esta revisión, entonces, encontré 4 solicitudes donde pasaba este patrón: la pantalla no mostraba nada, pero había tramos hijos cancelados sin OC/remito que correspondía mostrar.

Ahi ya quedó ajustado para que la pantalla revise el trámite completo (incluyendo los hijos):
- mantiene ocultos los tramos comprados, con OC o con remitos;
- muestra los tramos cancelados sin OC/remito, aunque sean tramos hijos;
- no toca los tramos que ya tienen compra o entrega asociada.
```

## Output Contract

Return only the rewritten message unless the user asks for explanation. Keep it ready to paste.

## References

- `references/alfabeta-laboratorios-example.md` — source example of Sergio's preferred style.
- `references/alfabeta-spec-monitor-examples.md` — internal/client examples for Sergio's monitor communication style.
- `references/alfabeta-guardrails-version-docs.md` — version README/changelog/mysql examples written by Sergio for Alfabeta guardrails.
