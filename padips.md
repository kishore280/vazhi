# padips.md — everything learned building this agent

## Docker

- **Dockerfile** builds an *image* (a recipe). **docker-compose.yml** runs *containers* from images, wires them together.
- `WORKDIR /app` sets the current directory inside the image. `COPY src dest` — `dest: .` means "into WORKDIR".
- Order matters for caching: `COPY requirements.txt .` + `RUN pip install -r requirements.txt` *before* `COPY package package` / `COPY server server`. Dependencies change rarely, code changes often — this way Docker reuses the cached pip-install layer unless `requirements.txt` itself changed.
- `pip install -r requirements.txt` — the `-r` flag means "read package list from this file". Without it, pip tries to install a package literally named `requirements.txt`.
- `services:` is a required top-level key in `docker-compose.yml` — service blocks can't float at the document root.
- **Named volumes** (`postgres_data:`) persist data across container recreation. Without one, a container's writable layer is wiped on `docker compose down` / rebuild.
- **`depends_on: condition: service_healthy`** — waits for a `healthcheck` to pass, not just for the container to start. A plain `depends_on` (no condition) only waits for "container started", which is too early for something like Postgres that takes a moment to accept connections.
- **`depends_on: condition: service_completed_successfully`** — waits for a service to run to completion and exit 0 (used for the one-shot migrator, so the API never starts against an unmigrated database).
- If you add a new file that a service needs (e.g. `worker_main.py`) but forget to `COPY` it in the Dockerfile, the image builds fine but the file is missing at runtime — `ModuleNotFoundError` only shows up when you actually try to run it.
- `env_file: - ./backend/.env` in compose passes secrets into a container without baking them into the image (unlike `COPY .env .`, which would leak the secret into the image layers).
- After rebuilding an image, old *containers* still run the old image until you `docker compose up -d --force-recreate` (or change something compose considers "config", which triggers auto-recreate).
- **One image, multiple services, different `command:`** — `backend` and `worker` build from the exact same `Dockerfile`/image, but `worker`'s compose entry overrides the command to `arq worker_main.WorkerSettings` instead of the default `uvicorn ...`. Same codebase, two different running processes.
- **A separate lightweight `Dockerfile.migrator`** for the one-shot migration service — installs only the 3 packages that `migrate.py` actually needs (sqlalchemy, asyncpg, pydantic-settings), not the full `requirements.txt` (torch, langgraph, etc.). That service's job is tiny and short-lived, so its image should be too.
- **`docker compose cp <local file> <service>:<path>`** — copies a file straight into a *running* container without rebuilding the image. Handy for one-off manual test scripts you don't want baked into the real image.

## Local venv vs Docker (easy to confuse)

- The local `.venv` inside `backend/` is **only** for the editor/type-checker (Zed, pyright) to resolve imports and give autocomplete. It has **zero effect** on what actually runs — Docker builds its own environment from scratch inside the image, reading only `requirements.txt`. Installing a package in `.venv` and forgetting to add it to `requirements.txt` means your editor sees no error, but the Docker build/run will fail with `ModuleNotFoundError`.
- `pyrightconfig.json`'s `"extraPaths": ["package"]` — tells pyright to also resolve imports from the `package/` folder, not just the project root. Needed because `vazhi.config` etc. live under `package/vazhi/`, not directly under `backend/`.
- `requirements.txt` pins: `==` is normal exact-version pinning. `===` is a rare "arbitrary equality" operator (different from `==`) — easy typo, causes pip to fail resolving in ways that look like a version doesn't exist.

## Editor tooling (Zed) — unrelated to the app itself but hit repeatedly

- Zed scopes its Python interpreter/venv picker to whatever it considers the "sub-project root." A subfolder needs **its own `pyproject.toml` file to exist** (content doesn't matter — even just `[tool.ruff]`, no `[project]` table) for Zed to treat it as its own sub-project and show that folder's `.venv` in the picker. Without it, Zed scopes to the worktree root and won't offer a nested `backend/.venv` at all.
- Separately: a nested `.venv` (one level below the worktree root) not being auto-detected, and the manual "Add Virtual Environment" picker being broken/incomplete, and toolchain selection not persisting across restarts — three distinct real upstream Zed bugs, not user error, confirmed via web search against Zed's own GitHub issues.

## FastAPI

- `APIRouter(prefix=..., tags=...)` — one file per concern (`system_router.py`, `agent_router.py`), mounted onto the app via `app.include_router(...)`. Keeps `main.py` thin.
- `Depends(require_uid)` — a dependency function's return value gets injected as an argument. Raising `HTTPException` inside it short-circuits the route entirely — the route body never runs.
- `Header(...)` (the `...` means required) — a *missing* header fails with `422` before your function body even runs. Only a *present-but-wrong* value reaches your code to produce `401`.
- Not every route needs auth — `/health` is deliberately public (monitoring tools have no credentials). Don't assume a pattern (`Depends(require_uid)` everywhere) generalizes without checking each route.
- Pydantic `BaseModel` request bodies — a field with no default is required; `field: str = "default"` makes it optional.
- `StreamingResponse` + an async generator function = how you stream a live response (used for SSE) instead of returning one JSON blob.

## Config pattern

- One centralized `Settings(BaseSettings)` class (`pydantic-settings`), not scattered `os.getenv()` calls. Fields get their values from environment variables automatically, with typed defaults.
- `model_config = SettingsConfigDict(env_file=".env", extra="ignore")` — also reads a `.env` file if present.
- A single shared `settings = Settings()` instance, imported wherever needed.

## Python packaging / imports

- Splitting an HTTP layer (`server/`) from business logic (`package/vazhi/`) — made importable via `PYTHONPATH=/app/package` (Docker) and `sys.path.insert(0, "package")` (defensive runtime fallback, so it works even if the env var isn't set).
- An empty `__init__.py` is what makes a folder a real importable Python *package*, not just a directory.
- `from __future__ import annotations` — makes type hints lazy (evaluated as strings, not immediately). Needed when a type hint references something only imported under `TYPE_CHECKING` (see below) — without it, Python tries to resolve the type at class/function *definition* time and crashes with `NameError` even though the code would otherwise never touch that import at runtime.

## SQLAlchemy / Postgres

- `create_async_engine(dsn, pool_pre_ping=True, pool_recycle=1800)` — a connection *pool*, not one connection. `pool_pre_ping` tests a connection before reuse (Postgres can silently drop idle ones). `pool_recycle` forces replacing connections older than N seconds.
- `async_sessionmaker(..., expire_on_commit=False)` — a session is "one unit of work" (a few queries, maybe a commit). `expire_on_commit=False` means you can keep reading an object's fields after commit without forcing a fresh DB read.
- `async with manager.get_session() as session:` — borrows a session from the pool, auto-returns it when the block ends.
- **`flush()` vs `commit()`**: `flush()` sends pending INSERT/UPDATE to Postgres *without* ending the transaction (so a new row's auto-generated `id` becomes available). `commit()` ends the whole transaction. A repository's `create()` method should `flush()`, not `commit()` — the caller (a service function) decides when the *whole* multi-table operation is done and commits once, so partial failures don't leave orphaned rows.
- Keyword-only arguments (`def foo(self, *, a, b)`) — the `*,` forces every caller to name arguments. Prevents silent bugs from positional args passed in the wrong order (e.g. swapping two same-typed string params).
- `with_for_update()` — locks the matched row(s) (`SELECT ... FOR UPDATE`) so no other transaction can touch them until this one finishes. Used to prevent two simultaneous requests from creating duplicate rows for the same brand-new conversation.
- `Base.metadata.create_all` only creates **missing tables**. It does NOT add new columns to a table that already exists from an earlier version. Adding a column to an existing table needs an explicit `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`.
- **Partial unique index** (`postgresql_where=...`) — an index covering only rows matching a condition. Used to enforce "only one *active* run per thread" at the database level (finished runs drop out of the index automatically), instead of "only one run ever."
- **Schema-version tracking, real vazhi's pattern**: a dedicated table (`vazhi_schema_migrations`) records which schema version is applied. A separate one-shot **migrator process** is the *only* thing allowed to create/alter tables, guarded by a Postgres **advisory lock** (`pg_advisory_lock`) so it's safe even if it gets run twice at once (e.g. container restart). The API/worker only ever *read-check* the version at startup (`require_current_schema`) and refuse to run on a mismatch — they never migrate themselves.
- **Repository pattern**: one class per table, the *only* place that writes queries for that table. Everything else calls the repository, never writes raw `select(...)` itself.
- **`BUSINESS_SCHEMA_VERSION` bump discipline**: every time a table or column is added to `models.py`, the version constant gets incremented too — that's the *only* signal that tells the migrator "there's new schema to apply." Forgetting to bump it means the migrator sees "already at current version" and silently skips creating the new table/column, even though the code now expects it to exist.

## Auth

- API-key auth via `Depends`, comparing against a value from centralized `Settings` — not a hardcoded string.
- Two failure modes to distinguish: missing credential (`422`, FastAPI's own validation) vs. wrong credential (`401`, your own code's decision).

## The queue / worker architecture (why it exists at all)

- An LLM call can take a long time. If the API answered it synchronously inside one HTTP request: (1) a dropped connection loses all progress, no way to reconnect, (2) the API process is blocked from doing anything else meanwhile.
- **Fix — split into two processes:**
  - **API**: fast, stateless. Saves the message, decides dispatch-vs-queue, returns immediately.
  - **Worker**: separate long-running process. Picks up queued work, does the slow part, writes the result back.
- The two only communicate through Postgres (source of truth for state) and Redis/ARQ (the job hand-off signal) — never a live in-memory connection between them.

## Queue intake logic

- **Idempotency**: every request carries a `request_id`. If the same `request_id` arrives twice (e.g. client retried after a timeout), return the *existing* result instead of creating a duplicate.
- **FIFO per thread, with a "steer" fast-lane**: normal messages queue in arrival order; a "steer" request always jumps to the front (used to interrupt an in-progress run — not fully wired up here, no active run yet to interrupt).
- Three queue policies: `enqueue` (wait in line), `reject` (fail immediately if anything's already active/queued), `steer` (jump the line, only valid if something is already running).
- "Commit to Postgres first, only then tell Redis about it" — a real run must exist in the database *before* a worker is told to look for it, or the worker could look for a row that isn't there yet.
- **`finalize_intake()` as a deliberately separate step**: it's called *after* `db.commit()` and *outside* the `async with manager.get_session()` block that did the writing — not folded into `intake_request()` itself. This is the concrete enforcement of the rule above: the enqueue-to-Redis call physically cannot happen before the commit, because it's a separate function call that only runs once the `async with` block (and its commit) has already finished.

## ARQ / Redis

- **ARQ** = a Python job-queue library, backed by Redis. `enqueue_job("function_name", args)` pushes work; a separate `arq worker_main.WorkerSettings` process consumes it.
- Every ARQ job function's first parameter is `ctx: dict` (shared worker state) — required by ARQ's calling convention even if unused.
- `WorkerSettings.functions = [...]` — mutable list as a class attribute triggers a linter warning (`RUF012`/similar) even though it's harmless here, since `WorkerSettings` itself is never instantiated — ARQ just reads the class attributes directly as a namespace. Fix (if you want to silence it): annotate with `ClassVar[list]`.
- Redis DSN format needs converting for different consumers: SQLAlchemy needs `postgresql+asyncpg://...` (the `+asyncpg` tells it which driver); a plain `psycopg`-based tool needs the DSN *without* that suffix — hence code that does `.replace("+asyncpg", "")`.

## LangChain vs LangGraph vs create_agent

- **LangChain** — base building blocks: a chat model wrapper, prompts, tool definitions. "Talk to an LLM" layer.
- **LangGraph** — built on LangChain. Models an *agent* as a graph of steps with persisted state: call model → maybe call tool → feed result back → repeat. The "advanced," stateful, loopable part.
- **`create_agent()`** (from `langchain.agents`) — a high-level convenience function. Give it a model + tools, it builds and runs a LangGraph graph for you without hand-wiring the graph yourself.
- Groq (and other providers) expose an **OpenAI-compatible API** — so you don't need a Groq-specific package, just `ChatOpenAI` pointed at Groq's `base_url`. Swappable by config, not code.

## LangGraph middleware pattern

- A middleware is a class (`AgentMiddleware` subclass) with hook methods that run at specific points in the agent's loop — e.g. `abefore_model` (right before calling the LLM), `aafter_model` (right after). Multiple middlewares stack — `create_agent(middleware=[...])` takes a list, and they wrap each other in order.
- `@hook_config(can_jump_to=["end"])` — declares that this specific hook is *allowed* to short-circuit the whole graph straight to a named point (here, `"end"`) instead of continuing normally. Returning `{"jump_to": "end"}` from the hook body actually does it.
- **`context_schema` vs `context`** — two different things passed at two different times. `create_agent(..., context_schema=VazhiContext)` just declares *the shape* of context this agent expects (a type declaration, checked once at agent-build time). The actual *instance* of that context — the real data for this specific run — gets passed later, at `agent.astream(..., context=context)` or `.ainvoke(..., context=context)`. Inside a middleware hook, that instance shows up as `runtime.context`.
- Why build the context object fresh per run instead of once: it holds per-run data (`run_id`, `thread_id`, `uid`) that's different every time `execute_agent_run` is called — it can't be a shared/global object.
- Middlewares can reach back into your own app's services from inside a hook (e.g. `SteerMiddleware` calls `should_end_run_for_steer()`, a Postgres-querying function you wrote) — a middleware isn't limited to pure LangGraph-internal logic, it's a real extension point into your own business logic.

## Checkpointer (cross-turn memory)

- Without a checkpointer, every `agent.ainvoke(...)` call starts completely fresh — zero memory of prior turns, even on the "same" conversation.
- `AsyncPostgresSaver` (from `langgraph-checkpoint-postgres`) persists conversation state to Postgres. Pass it to `create_agent(..., checkpointer=checkpointer)`.
- `config={"configurable": {"thread_id": ...}}` — this is how the checkpointer knows *which* conversation's history to restore. Same `thread_id` → same restored state.
- Because of this, you only ever send the **new** message each turn — the checkpointer prepends everything before it automatically. Sending full history manually would double it up.
- The checkpointer needs its own connection pool (`psycopg`-based, not SQLAlchemy's asyncpg-based engine) because `AsyncPostgresSaver` is a separate library with its own connection requirements.
- **Advisory lock for one-time setup**: `checkpointer.setup()` creates the checkpoint tables. Locked (a different key than the schema-migration lock, so they can't collide) so it's safe to call on every worker/API startup — the actual table-creation SQL only really runs once.

## SSE (Server-Sent Events)

- A simple one-way streaming protocol over plain HTTP: lines of `event: <type>`, `data: <json>`, blank line to end an event. Any line starting with `:` is a comment (used for heartbeats to keep the connection alive during silence).
- The worker doesn't talk to the client directly — it publishes events to a **Redis Stream** (`redis.xadd(...)`) as it generates each token. The API endpoint separately reads that stream (`redis.xread(...)`) and forwards entries to the client as SSE, using `StreamingResponse` + an async generator.
- `agent.astream(..., stream_mode="messages")` yields `(message_chunk, metadata)` tuples as tokens are generated — instead of `ainvoke()`'s single blocking wait for the full reply.
- This decoupling (worker → Redis → API → client) means the client can disconnect and reconnect without losing the run — it just re-reads the same Redis Stream from where it left off (`Last-Event-ID`).

## Subagents (task delegation)

- A subagent call is not a nested function call inside the same process — it's a **real, separate `AgentRun`**, dispatched through the exact same queue/worker infrastructure as any top-level message. It gets its own row, its own thread, its own worker pick-up. The only thing making it "sub" is `parent_run_id` pointing back at the run that spawned it.
- **`SubagentThread`** exists purely so a subagent conversation can be *continued* later — it maps a deterministic `child_thread_id` (hashed from parent thread + subagent slug + tool call ID) back to which parent/subagent spawned it, so a later `task` call with the same `thread_id` picks up the same conversation instead of starting fresh.
- **Busy detection**: before starting a subagent run, check `get_active_run_by_thread_for_user` on the child thread — if something's already running there, refuse (`SubagentRunBusy`) instead of silently queuing behind it. Subagent calls use `queue_policy="reject"` for exactly this reason — a subagent thread should never build up a backlog.
- **Sync tool vs background tools**: the `task` tool blocks — it calls `await_agent_run_result()` and doesn't return to the model until the subagent finishes (or times out). `subagent_start`/`subagent_status`/`subagent_cancel`/`subagent_await` are the *async* alternative — start it, keep working, check back later. Real use case: fire off 3 independent subagent tasks in parallel with `subagent_start`, keep doing other work, `subagent_await` each when you actually need its result.
- **A parent must be `"running"` before it can spawn a subagent.** This isn't a made-up rule — it's the real gate `SubagentRunService.start()` checks (`creator_run.status != "running": raise`). This is why the worker has to mark a run `"running"` and *commit that immediately*, before doing any of the actual LLM work — a subagent tool call happening mid-stream needs to see that status from a completely separate database session.
- **`hash_id()` for deterministic IDs**: `subagent_child_thread_id()` hashes `(parent_thread_id, agent_slug, tool_call_id)` into a stable ID. Same inputs always produce the same thread ID — this is what makes "call the same subagent with the same tool call" naturally idempotent (a retried tool call reuses the same child thread instead of creating a duplicate).
- **Scoped lookups prevent cross-conversation leaks**: `get_subagent_run_for_creator(run_id, uid, created_by_run_id)` only returns a run if its `parent_run_id` matches. A tool call can't check the status of some other conversation's subagent run just by guessing/reusing a `run_id`.
- **Subagents reuse the exact same `intake_request()` a normal top-level message goes through** — just called with `queue_policy="reject"` and `parent_run_id` set. This isn't a separate, parallel code path; it's the same function. Practical payoff: the subagent thread gets the "one active run per thread" database-level protection *for free* — nothing extra had to be built for that, because a subagent's thread is just a thread like any other, and that constraint already applies to every thread.
- **One-level recursion limit, enforced explicitly**: `SubagentRunService.start()` checks `if creator_run.parent_run_id is not None: raise ValueError(...)` — a subagent can never itself start another subagent. This is a flat depth cap (subagents can't nest), not a counter that would allow limited nesting depth. Prevents a runaway delegation chain (subagent spawns subagent spawns subagent...) with one simple check, at the cost of not supporting genuinely nested delegation if that were ever needed.

## Worker reliability (leases, heartbeats, retries)

- **A "lease" is a claim with an expiry.** When a worker picks up a run, it doesn't just say "I own this" — it says "I own this *until timestamp X*." If the worker dies, nothing renews that timestamp, and after it passes, the run is fair game for someone else to notice and clean up. This is fundamentally different from a lock with no expiry, which would leave a run stuck forever if its owner died.
- **Heartbeat = proof of life, running in the background.** `asyncio.create_task(_heartbeat_loop(...))` starts a loop that runs *concurrently* with the actual LLM work, periodically extending the lease. It's launched with `create_task`, not `await`ed directly, specifically so it runs alongside the main work instead of blocking it.
- **`stop_heartbeat = asyncio.Event()`** — a signal used to cleanly stop a background task. `stop_heartbeat.set()` flips it; the loop checks it each cycle (`while not stop.is_set()`) and exits. `await heartbeat_task` after that makes sure it's *actually* stopped before moving on — without this await, the task could still be mid-iteration when the function returns, a subtle bug (using a database session that's about to close).
- **`AgentRunAttempt` is a fact table, not a status field.** Every time a run gets picked up — even the same run retried after a failure — that's a new row: attempt #1, attempt #2, etc. `AgentRun` itself only ever holds the *current* status; `AgentRunAttempt` is the permanent history of every lease anyone ever held on it, useful for debugging "why did this take 3 tries?"
- **`worker_id` as an ownership check, not just a label.** `mark_terminal(run_id, worker_id=owner_token, ...)` refuses to finalize the run if `run.worker_id != worker_id`. This matters when a lease expires and a *different* worker takes over: if the original (slow, presumed-dead) worker eventually finishes and tries to write its result, that write is silently rejected — the new owner's result is what counts, not a stale duplicate.
- **Retryable vs permanent failure**: a database connection blip (`OperationalError`) or timeout is *not the agent's fault* — retrying probably succeeds. A logic bug in your own code retrying won't help. `_is_retryable_exception()` draws that line explicitly; only the retryable category gets `release_lease_for_retry()` (reset to `"pending"`, so ARQ redelivers it as a new attempt) instead of a permanent `"failed"`.
- **`reconcile_expired_run_leases()` is a periodic sweep, not per-run logic.** It doesn't run as part of any one run's lifecycle — it's a separate function, on a timer, scanning *all* runs for ones stuck at `"running"` with an expired, unrenewed lease. This is the actual safety net for "the worker process itself crashed" (heartbeat loop and worker_id checks handle graceful failures; this handles the ungraceful ones).

## Multi-mode streaming (`stream_mode=["updates", "messages"]`)

- `agent.astream(..., stream_mode="messages")` alone only shows you token-by-token text deltas — it does NOT show you anything a middleware writes into LangGraph *state* via a `Command` update (e.g. `TokenUsageMiddleware` writing a usage snapshot). That only shows up in `"updates"`-mode chunks.
- Passing a **list** of modes (`stream_mode=["updates", "messages"]`) makes `astream` yield `(mode, chunk)` tuples instead of just `chunk` — you check `if mode == "messages":` vs `if mode == "updates":` (or just check `isinstance(chunk, dict)`) to know which kind of chunk you're looking at, and handle each differently in the same loop.
- **This is exactly why the loop had to grow, not because the earlier single-mode version was wrong.** When the loop was first written, nothing wrote to state via `Command` — `"messages"` alone was the correct, complete subset for what existed then. Once `TokenUsageMiddleware` was added (writes state via `Command`), the loop needed `"updates"` mode too, or that data would just be silently dropped. Same "build the exact subset needed now, expand exactly when the next piece needs it" pattern used everywhere else in this project — not a bug fixed, a natural growth point.
- `"updates"`-mode chunks are `{node_name: node_output_dict}` — you loop over `chunk.values()` (or `.items()` if you need the node name) and pull whatever key you're interested in (e.g. `node_output.get("token_usage")`) out of each node's output dict.

## Observability / token accounting (TokenUsageMiddleware)

- The middleware doesn't return usage data to your code directly — it writes a snapshot into LangGraph **state** after every model call (`wrap_model_call` returns an `ExtendedModelResponse` wrapping a `Command(update={"token_usage": snapshot})`). Your worker loop has to actively watch for that state update (see multi-mode streaming above) and pull the numbers out — nothing pushes them to you automatically.
- **Real vs. estimated tokens**: the snapshot includes both. `usage_metadata` on the model's response `AIMessage` is the *real*, provider-reported number (what you actually get billed for). Everything else in the snapshot (context-window usage ratio, message counts, etc.) is *estimated* via `count_tokens_approximately` — a rough heuristic, not what the provider actually counted. The middleware clearly separates the two rather than pretending an estimate is exact.
- **Run-level vs Thread-level aggregation**: `before_agent` resets the Run-level total to zero at the start of every run, but *keeps* the Thread-level total running across every run that's ever happened on that thread — one counter answers "how much did *this* turn cost," the other answers "how much has this whole conversation cost so far."
- Real usage data only lands in your own database (`AgentRun.token_usage` column) if your worker code explicitly captures it from the stream and passes it into whatever function persists the run's final state (`mark_terminal(..., token_usage=token_usage)` here) — building the middleware alone does nothing to your own tables until you wire that last step through.

## Full conversation history reload

- Separate from SSE/resume — SSE only ever restores the *currently streaming* run; a full history reload (`GET /thread/{id}/history`) is for a cold page load, reconstructing the entire conversation from scratch by querying every `Message` row for that thread, ordered by time.
- Joining in `AgentRun` timing (`run_started_at`/`run_finished_at`) onto each message via its `run_id` lets a frontend show "this reply took N seconds" without a separate request per message — one query, one join, not N+1 queries.

## "Port but don't wire in" — a real, valid finished state

- Not every ported file needs to be *active* to be "done." Real vazhi's own `tool_approval.py` exists, is fully correct, and is deliberately NOT wired into the active middleware list — because the plumbing it depends on (persisted approval state, an API endpoint to submit a decision, a frontend UI) doesn't exist yet in the reference implementation either. Wiring a HumanInTheLoopMiddleware in without a way to ever resume it would make every gated tool call hang the run forever.
- Matching a reference project exactly sometimes means matching its *incompleteness*, not just its finished features — building a file that exists-but-inert, because that's genuinely what the source does at this point in its own development, not skipping it and not force-completing it either.

## ARQ cron jobs

- `arq.cron(func, second={0, 15, 30, 45})` — schedules a function to run at those specific seconds of every minute (here: every 15 seconds), independent of any job queue — it's a timer, not a queued task.
- `WorkerSettings.cron_jobs = [...]` — a second list alongside `functions`, for scheduled/periodic work rather than on-demand jobs triggered by `enqueue_job`.
- A worker health heartbeat (`redis.set(WORKER_HEALTH_KEY, "1", ex=30)`) is itself a cron job — it exists purely so a separate `/ready` endpoint can check "has *any* worker process reported alive in the last 30 seconds?" without the API ever talking to the worker directly.

## Type-checking gotchas hit this project

- A mutable class-level default (`functions = [...]`) on a class that's never instantiated is a false-positive lint warning — fix by annotating `ClassVar[list]` if you want it silenced.
- Third-party library **type stubs can be narrower than the actual runtime behavior** — e.g. `psycopg`'s `Connection.execute()` stub only declares a `Template` argument type, but the real implementation also accepts a plain `str`. When you've verified at runtime that it works, a `# pyright: ignore[...]` comment is the correct fix — not restructuring working code to satisfy an overly-strict stub.
- A field typed `int | None` can't be passed directly to a function expecting plain `int` — even if you "know" it's always set in practice, add an explicit `if x is None: return` guard so the type checker (and any real edge case) is handled honestly.
- Annotating a plain dict literal with its expected `TypedDict` type (e.g. `config: RunnableConfig = {...}`) is often the actual fix for "dict not assignable to X" errors — same value at runtime, just a type hint the checker can now recognize.
- **List invariance strikes again**: `middleware=[SteerMiddleware()]` inline fails type-checking against a parameter expecting `list[AgentMiddleware[Any, Any, Any]]`, even though `SteerMiddleware` *is* an `AgentMiddleware`. Same root cause as the `AsyncConnectionPool` issue earlier — Python's generic lists don't auto-widen. Fix: assign to a separately-annotated variable first (`middleware: list[AgentMiddleware[Any, Any, Any]] = [SteerMiddleware()]`), then pass that variable in.
- **Editor autocomplete can suggest a completely wrong import** — typing `Any` and accepting the first autocomplete suggestion pulled in `from re import A` (the regex `ASCII` flag, not even the same name!) and `from langgraph.channels.untracked_value import Any` (a random internal module that happens to also define something called `Any`) instead of the real `from typing import Any`. Both would likely still "work" by accident here (only used in an erased type hint), but always double-check *where* an auto-import actually came from, especially for common short names like `Any`.

## Git / project hygiene

- Always create a `.gitignore` (with `.env` in it) *before* writing any file containing a real secret/API key — otherwise there's a real risk of committing it.
- `git status --short` after a broad change — quickly shows what's actually new/modified before staging anything.

## General workflow lessons from this project

- **Check the real reference implementation's exact structure before building the next piece** — don't build a simplified version now and "fix it properly later." Applies to code patterns (centralized config vs scattered env reads) and file/folder organization (router-per-file vs everything in `main.py`) equally.
- **Don't assume a pattern generalizes without checking per-instance** (e.g. auth on "almost every route" doesn't mean *every* route).
- When a real reference file is large and built in stages, build only today's needed subset **in its exact final form** — not a placeholder that gets rewritten later. Leave out only the parts that depend on pieces which don't exist yet, and add them back verbatim once their prerequisite is built.
- A file that imports something not yet installed/built (e.g. `run_worker.py` importing the full middleware stack) can't be "the next step" just because the docs list it next — check its actual imports before committing to an order.
- Always verify a piece **live** — a curl request, a direct database query, a manually-run script — rather than trusting "it should work" from reading the code.
