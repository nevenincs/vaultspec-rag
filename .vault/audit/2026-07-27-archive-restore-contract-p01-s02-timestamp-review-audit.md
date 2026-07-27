---
tags:
  - '#audit'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `archive-restore-contract` audit: `p01 s02 timestamp review`

## Scope

Reviewed `P01.S02`'s archive-owned completion clock in `write_snapshot_manifest`, its unit guard, and the recorded mutation proof against the accepted retention-clock contract.

## Findings

### completion-clock-guard | medium | The timestamp guard does not prove the UTC or archive-age requirements it claims to cover

`write_snapshot_manifest` stamps an aware UTC ISO-8601 instant after the archive directory is prepared and before the atomic manifest publication. The initial guard accepted any offset-aware instant and did not create a deliberately old archive artifact, so it could not distinguish the intended clock from a copied-source-time regression.

Resolved in `P01.S02`: the guard now asserts a zero UTC offset and places a copied metadata artifact with a 31-day-old mtime beside the manifest. It asserts the stamp remains within the write interval, and records focused failures for an absent field and a deliberately backdated stamp before the restored green run.

## Recommendations

No further action for `P01.S02`. `P01.S05` must still exercise this stamp through whole-directory retention, including the old-metadata case named in the plan.
