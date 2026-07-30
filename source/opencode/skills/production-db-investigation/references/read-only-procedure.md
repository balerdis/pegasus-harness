# Production Read-Only Procedure

## Scope

This file is the canonical procedure for direct SQL investigation in Leannec-managed production systems. It governs target selection, access, runtime selection, bootstrap safety, SQL validation, execution limits, and evidence handling.

## Authority

Follow this procedure exactly. Any failed or uncertain gate stops the investigation. Session-level read-only mode is defense in depth, never a substitute for statement validation.

## Access Envelope

1. Select exactly one target system and resolve its host and document root together only from this table:

| Target system | Production host | Document root |
| --- | --- | --- |
| Osfatun | `osfatun-prod` | `~/web` |
| Ospreviene | `ospreviene-prod` | `~/web` |
| Obra Social / obra-social | `obrasocial-prod` | `~/web/www` |
| Leannec | `leannec-prod` | `~/web/www` |

If the system is missing, ambiguous, or outside this allowlist, stop before access. Treat each row as one allowlisted tuple; never infer or derive a host or document root from user input, a database name, or a code path.
2. Connect only through `ssh gitlab-leannec`, then to the single resolved production host.
3. On that host, inspect its deployed code and DB/config only within the document root resolved from the same table row. Do not bypass either hop, use local checkout assumptions, or cross hosts/databases unless explicitly required by the investigation.
4. Inspect deployed code and real schema first. Do not modify deployed files.
5. PHP CLI may default to 7.4. Use `PHP_BIN=/usr/bin/php8.4` and invoke it with `-d short_open_tag=On`; the production systems require PHP short tags. Verify compatibility before loading application code, and fail closed if the effective value is not enabled.
6. Reuse connectivity from `DOCUMENT_ROOT_FROM_TABLE/custom/config/db.ini.php` through the approved application environment, after replacing the marker with the exact document-root literal from the selected table row. Never print, copy, parse into output, or persist its secrets.

## SSH Transport Gate

Keep the PHP payload separate from the SSH command. Never embed PHP, SQL, config, or secrets in a remotely quoted command string.

Prefer ProxyJump only after proving that the target alias resolves through the configured jump path:

In the command templates, replace the non-executable markers `HOST_FROM_TABLE` and `DOCUMENT_ROOT_FROM_TABLE` with the exact host and document-root literals from one target-table row. Never mix rows, derive either value from user input, use shell interpolation for selection, or execute a template before every marker it contains is replaced.

```sh
ssh -T -o BatchMode=yes -J gitlab-leannec HOST_FROM_TABLE /usr/bin/php8.4 -d short_open_tag=On <<'PHP'
<?php
fwrite(STDOUT, "transport-ok\n");
PHP
```

`-J gitlab-leannec` is mandatory in this form: it preserves the required transit through that host. If target resolution or forwarding fails, stop that attempt; do not bypass the jump host.

If the resolved host does not resolve through `ssh -J`, use this tested transport shape, which sends stdin through the outer SSH process into a second SSH process without shell metacharacters or nested quoting. Prove the fallback independently for the resolved host; prior success for another host is not evidence:

```sh
ssh -T -o BatchMode=yes gitlab-leannec \
  ssh -T -o BatchMode=yes HOST_FROM_TABLE /usr/bin/php8.4 -d short_open_tag=On <<'PHP'
<?php

declare(strict_types=1);

$documentRoot = 'DOCUMENT_ROOT_FROM_TABLE';
if (!str_starts_with($documentRoot, '~/')) {
    throw new RuntimeException('Document root must be the allowlisted home-relative literal.');
}
$documentRoot = (string) getenv('HOME') . substr($documentRoot, 1);

if (!chdir($documentRoot)) {
    throw new RuntimeException('Approved production working directory is unavailable.');
}

// Add only the bootstrap already approved by the Bootstrap Safety Gate.
// Keep the validated, single read-only statement in PHP, not in the SSH command.
throw new RuntimeException('Runner is inert until all read-only gates pass.');
PHP
```

The quoted heredoc delimiter makes the local shell pass the body literally: no variable, command, or backslash expansion occurs. Both remote commands contain only fixed executable arguments. The runner remains ephemeral because PHP reads it directly from stdin; do not redirect it to a production path or use `tee`, `scp`, `sftp`, or a temporary file.

Before adding bootstrap or SQL, use the `transport-ok` body in whichever SSH form passed its resolution gate. Optionally compare a harmless payload hash locally and through the same two-hop route using `sha256sum`; hashes must match exactly. This gate may prove transport only. It must not read configuration, connect to the database, or display environment values.

## Bootstrap Safety Gate

Inspect every deployed bootstrap/include before loading it. Prove the selected minimal include path initializes only required configuration, autoloading, and DB connectivity without requests, teardown effects, hooks, events, writes, jobs, or external calls. If that proof is unavailable, stop before execution.

Use the stdin transport template above for a minimal ephemeral read-only runner so no production file exists to remove. Do not use application models, repositories, controllers, scripts, jobs, endpoints, or helpers that may persist or trigger side effects.

## Statement Guard

Permit only one bounded investigative statement at a time whose top-level operation is `SELECT`, `SHOW`, `DESCRIBE`, or `EXPLAIN`; permit `information_schema` reads. The session read-only command below is the sole control-statement exception. Parse and validate the full statement, including comments, strings, CTEs, subqueries, and functions. Reject stacked statements and anything not demonstrably read-only.

Reject `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `MERGE`, `CALL`, `DO`, DDL, grants, administration, explicit locks, temporary tables, dumps, `LOAD DATA`, `LOAD_FILE`, `INTO OUTFILE`, all other file reads/writes, user variables with side effects, persistent/global `SET`, and any function or construct that may mutate state. Reject `FOR UPDATE`, `LOCK IN SHARE MODE`, unbounded scans, and transactions or queries likely to block.

Before queries, request session-only read-only transaction mode using the connection's supported equivalent, such as `SET SESSION TRANSACTION READ ONLY`. If unavailable or rejected, stop. Never weaken validation because this guard succeeded.

## Bounded Investigation

- Require exactly one target system, its table-resolved host and document root, and one target DB on that host. Cross-host or cross-database reads require explicit investigative necessity.
- Start with deployed code and narrowly scoped schema metadata. Then filter by exact IDs and use a reasonable `LIMIT`.
- Select only needed columns. Avoid PII; redact sensitive values in notes and output.
- Stop rather than broaden into large scans, exports, dumps, or speculative discovery.

## Evidence

Record conceptually each executed statement, target DB, purpose, bounds, row count, and sanitized finding. Never record credentials or DSNs. Separate confirmed facts, hypotheses, and the next read-only step. Do not repair production.
