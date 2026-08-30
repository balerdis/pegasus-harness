---
name: playwright
description: Drives a real browser to exercise and inspect the pages a project renders
distribution: npm
endpoint: https://registry.npmjs.org/@playwright/mcp/-/mcp-0.0.79.tgz
package: "@playwright/mcp"
version: 0.0.79
integrity: sha512-VpqD4a3vFyGQMY9sh3UJiO6wjcurggkljKfAyCHL0QWGY5m6Ehr3MNsAAHPDHO//n13g0PCjpHatAOiulrqdZQ==
entry: cli.js
lockfile: playwright-package-lock.json
---

# Playwright Convention (browser automation)

Playwright drives a real browser against a real page: navigating, clicking, filling
forms, reading back what actually rendered, and capturing a screenshot or the
console's own output. It is the one server here that touches a UI at all -- every
other tool in this project reasons about source, structure, or memory, never about
a page as a user's browser would show it.

Reach for it when a phase needs to know what a browser does with a page, not what
the source says it should do: confirming a change renders, walking a flow no test
suite exercises yet, reading a runtime console error, or capturing a screenshot to
show what changed. Prefer it over guessing from markup or from a component's own
source whenever the question is really "what does this look like, and does it
work" rather than "what does this code say".

Playwright is a browser, not a test runner and not a source of truth about
intent. It proves that a page rendered, a click landed, or a console stayed quiet
-- never that the result was the *right* one; that judgment stays with whoever
asked the question. And it is not where a project's own automated tests belong:
authoring or running this project's test suite is a different job, done through
its own tools, even when the suite in question happens to open a browser too.

## Before Automating a Page

- Prefer a snapshot or a targeted read over a screenshot when the question is
  about structure or text -- a screenshot proves how something looks, not what
  it is.
- Navigate to a known state before acting on it. A click, a fill, or a read
  against a page whose state was never confirmed is a guess wearing the shape of
  a fact.
- Close what was opened once the question is answered. A browser left running is
  a resource nothing after this session is watching.

## When Not to Use It

- Questions a file read or a grep already answers -- a browser is for what only
  rendering can show.
- This project's own automated test suite, even one written against this same
  browser -- that is authored and run through its own tooling, not driven ad hoc
  through this server.
- Anything that would submit real credentials, payment details, or another
  person's data through a page this session does not own the consequences of.
