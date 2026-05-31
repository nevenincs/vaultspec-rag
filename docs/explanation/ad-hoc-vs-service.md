# Ad-hoc vs service mode

vaultspec-rag offers the same search two ways: as a one-shot command that loads
everything fresh, or as a long-lived service that loads once and answers for
the lifetime of the process. The two modes return identical results from
identical files. The only thing that differs is process lifetime, and that
difference reshapes when each mode is the right fit.

## The shape of the cost

Search has two costs. Loading the models is slow: several seconds of GPU
initialization, weight transfer, and CUDA warmup. Running a query against
already-loaded models is fast: well under a second, often a few hundred
milliseconds. Ad-hoc mode pays the slow cost on every invocation. Service mode
pays it once at startup and then handles each query at the fast cost for as
long as the process lives.

That asymmetry is the whole story. Everything else - flags, modes, the
fallback policy - follows from it.

## When ad-hoc is the right choice

Ad-hoc mode suits searches that happen rarely and stand alone. A nightly cron
that runs one query and exits. A quick manual lookup in a project you rarely
touch. A CI step that grabs context once per build. An environment where
keeping a resident process around isn't acceptable: locked-down servers,
ephemeral containers, anywhere process budgets are tight.

In those cases the loading cost is unavoidable but also infrequent, and the
operational simplicity of "command in, results out, nothing left behind" is
worth the seconds.

## When service mode is the right choice

Service mode suits anything that searches more than once a minute. Interactive
development where the same person fires off queries throughout the day. AI
assistants and agent loops that call the tool repeatedly within a single task.
Editor integrations that trigger searches on demand. A multi-project workflow
where switching contexts shouldn't mean paying the warmup tax each time.

The first query still pays the loading cost. Every query after that runs at
the fast cost, and the difference compounds quickly.

## Same backend, different lifetime

Both modes read the same index files, encode queries with the same models, and
rank with the same algorithm. A query that finds a result ad-hoc finds the
same result through the service, at the same score. There's no "service mode
search" and "ad-hoc search" as separate features; there's one search engine
with two ways to host it.

## Why `search --port` won't quietly fall back

The local Qdrant store holds an exclusive file lock. Only one process at a
time can open it. If the resident service holds that lock and a `--port`
command silently fell back to in-process mode when the service was
unreachable, the fallback would grab the lock and strand the service - which
would then fail every subsequent query until it was restarted.

The explicit hard-fail prevents that. If you ask for the service and the
service isn't there, the command stops rather than corrupting state. The
`--allow-fallback` flag exists for cases where you've decided the trade-off is
acceptable, and it's opt-in so the decision is always visible.

## Project slots, briefly

The service holds a small in-memory workspace per project it has searched: the
indexer state, the per-project graph, the file watcher. Idle workspaces get
evicted after a TTL so the service doesn't grow unbounded. Slots aren't
something to manage; they're how the service scales to several projects
without reloading anything you've recently touched.
