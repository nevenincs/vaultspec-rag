---
tags:
  - '#audit'
  - '#test-marker-taxonomy'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:1a9c83d5a09780c71250bbc58111662207be22ce63a0815b49fda3c706fcf738'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `test-marker-taxonomy` audit: `weight and kind marker axes, and the integration selection leak`

## Scope

An examination of how tests are selected for the project's only real gate. There is no continuous-integration workflow running the suite, so the local recipe IS the gate, and what that recipe selects is what the project actually verifies.

The examination was prompted by a recipe change that widened the default selection from one marker expression to another, and by the subsequent observation that a run intended as a unit gate was starting a web server per test and projecting to roughly three hours. Counts below were measured by collection rather than inferred.

## Findings

### integration-tests-leak-into-the-default-selection | high | Two hundred and thirty-two tests in the integration directory run on every default invocation of the gate

The integration directory collects seven hundred and sixty-five tests. The integration marker selects five hundred and thirty-three of them. The remaining two hundred and thirty-two are reachable by a selection that excludes the integration marker, so they execute on every default run of the gate.

Twenty of the seventy-four files in that directory never reference the integration marker at all. Of the leaking tests, roughly a hundred and forty-six carry no marker of any kind, about forty-seven carry a subprocess-and-GPU marker whose own documentation says it should be run separately from integration - and which therefore does not exclude them either - and the remainder carry only a kind marker. This is not a harmless miscategorisation: a spot check of the quality module found it marked for kind alone while its fixtures construct a real embedding model and a real vector store. Genuinely heavyweight, GPU-backed work is running under what the recipe advertises as the fast default.

### no-directory-marking-mechanism-exists | medium | The absence is a mechanism never built, not a hook that broke

Neither the root test configuration nor the integration directory's own configuration defines a collection-modification hook, an add-marker call, or a module-level mark list. Every marker in the suite was applied by hand, per file, and twenty files simply never received one.

The obvious minimal fix does not work and would fail silently if attempted: a module-level mark list declared in a directory's configuration file applies only within the module that declares it and does not propagate to sibling test modules in that directory. The correct minimal mechanism is a collection-modification hook that inspects each collected item's path and adds the marker additively, so a test keeps whatever kind marker it already carries and gains the weight marker alongside it.

### marker-taxonomy-conflates-two-axes | medium | Weight and kind are independent axes, but only one is ever required, so a test can opt out of weight by declaring kind

The registered markers span two unrelated questions: how expensive a test is to run, and what aspect of the system it verifies. Nothing requires a test to answer the first. Six files answer only the second, and all six are real, heavyweight, GPU-backed tests that silently escaped the weight axis by declaring a kind.

No enforcement exists anywhere: the configuration registers the marker names but sets no strict-marker option, no default selection, and no required declaration. Selection is expressed only in the recipe, which is why the gate's meaning can change without any test changing. The subprocess-and-GPU marker compounds this by documenting an intent - that it be run separately from integration - which the current recipe does not honour, leaving it ambiguous whether that marker is a third exclusion the recipe needs or evidence that the axes must be stated explicitly before any recipe can select correctly.

## Recommendations

Separate the mechanical repair from the policy question, and do not let the first stand in for the second.

The mechanical repair is safe and small: add a collection-modification hook to the integration directory's configuration that additively marks every item collected beneath it. That closes the two-hundred-and-thirty-two-test leak in one place without touching any test. It should be taken promptly, because until it lands the project's only gate is running heavyweight GPU work on every invocation while reporting itself as the fast default.

The policy question needs a decision record rather than another recipe edit. It must state what the axes are, whether declaring weight is mandatory and how that is enforced rather than merely intended, whether a hook applies a default or rejects an unmarked test outright, and whether the subprocess-and-GPU marker constitutes a second default exclusion. The reason to decide rather than patch is specific and has already happened once: the gate's selection was widened by a recipe change made in good faith on incomplete information about the taxonomy, and a second silent recipe patch over the same unexamined taxonomy is how this identical gap reopens under a different marker.

One consequence worth stating for whoever writes that record: because no continuous-integration workflow runs this suite, the selection expression in the recipe is not a convenience, it is the definition of what the project verifies. It deserves the same scrutiny as the code it gates.
