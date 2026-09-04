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

## Type-checking gotchas hit this project

- A mutable class-level default (`functions = [...]`) on a class that's never instantiated is a false-positive lint warning — fix by annotating `ClassVar[list]` if you want it silenced.
- Third-party library **type stubs can be narrower than the actual runtime behavior** — e.g. `psycopg`'s `Connection.execute()` stub only declares a `Template` argument type, but the real implementation also accepts a plain `str`. When you've verified at runtime that it works, a `# pyright: ignore[...]` comment is the correct fix — not restructuring working code to satisfy an overly-strict stub.
- A field typed `int | None` can't be passed directly to a function expecting plain `int` — even if you "know" it's always set in practice, add an explicit `if x is None: return` guard so the type checker (and any real edge case) is handled honestly.
- Annotating a plain dict literal with its expected `TypedDict` type (e.g. `config: RunnableConfig = {...}`) is often the actual fix for "dict not assignable to X" errors — same value at runtime, just a type hint the checker can now recognize.

## Git / project hygiene

- Always create a `.gitignore` (with `.env` in it) *before* writing any file containing a real secret/API key — otherwise there's a real risk of committing it.
- `git status --short` after a broad change — quickly shows what's actually new/modified before staging anything.

## General workflow lessons from this project

- **Check the real reference implementation's exact structure before building the next piece** — don't build a simplified version now and "fix it properly later." Applies to code patterns (centralized config vs scattered env reads) and file/folder organization (router-per-file vs everything in `main.py`) equally.
- **Don't assume a pattern generalizes without checking per-instance** (e.g. auth on "almost every route" doesn't mean *every* route).
- When a real reference file is large and built in stages, build only today's needed subset **in its exact final form** — not a placeholder that gets rewritten later. Leave out only the parts that depend on pieces which don't exist yet, and add them back verbatim once their prerequisite is built.
- A file that imports something not yet installed/built (e.g. `run_worker.py` importing the full middleware stack) can't be "the next step" just because the docs list it next — check its actual imports before committing to an order.
- Always verify a piece **live** — a curl request, a direct database query, a manually-run script — rather than trusting "it should work" from reading the code.
