# Evals

Run against a model before adopting it.

    python tests/evals/run.py --model <name> --tag core
    python tests/evals/run.py --models a,b,c --repeat 3 --json results/cmp.json

`--tag core` is the offline suite. `--with-mcp` enables the two web tasks.

Scoring is on filesystem state and tool calls, never on prose, except where
prose is the point ("did it admit the file was missing").

Add a task by dropping a JSON file in `tasks/`. Fields: `id`, `prompt`,
`setup` / `setup_generated`, `checks`, `max_steps`, `timeout`, optional
`confirm`, `persona`, `requires`, `tag`.

Check kinds: `file_exists`, `file_absent`, `file_contains`, `file_matches`,
`file_equals`, `response_contains`, `response_matches`, `tool_called`,
`tool_not_called`, `no_error_events`.