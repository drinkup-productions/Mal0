"""System prompt assembly."""
from . import memory, personas, feedback, presence
import time

SHELLS = {
    "windows": ("the platform shell - Windows PowerShell 5.1",
                "- The shell is PowerShell 5.1: chain with ; not &&, use Get-ChildItem not ls."),
    "android": ("the platform shell - Android sh",
                "- The shell is Android sh: chain with ; or &&, use ls and find."),
}


TOOL_GUIDE = """
TOOLS
Core tools, always available:
  read(path, offset, limit)   read a file with line numbers, or list a folder
  tail(path, n)               the last n lines of a file - use this for logs
  write(path, content)        create or overwrite a whole file
  edit(path, old, new)        replace one exact block; include unique context
  bash(command, cwd)          @SHELL@         
  remember(text)              append one durable fact to your notes

Everything else is an MCP tool, named server__tool.

WEB SEARCH
Use ddg__search first. It returns real URLs with redirects already resolved.
  1. ddg__search(query="...", max_results=8)
  2. Copy the best URLs CHARACTER FOR CHARACTER.
  3. fetch each with max_length=60000.
  4. If a fetch stops mid-sentence, fetch again with start_index set to how much
     you have already read. Keep going until you have the whole thing.
  5. Follow "next" / "part 2" links. Guides are paginated.

FETCH ARGUMENTS
  max_length defaults to 5000, far too small for an article. Always pass
  max_length=60000. Hard cap is 1000000. start_index resumes a long page.

URL DISCIPLINE
  - Never type a URL from memory. Copy it out of the tool output.
  - DuckDuckGo links look like //duckduckgo.com/l/?uddg=https%3A%2F%2F...
    Fetch the whole string as-is.
  - One 404 is not proof a link is dead. Retry once, exactly. Only then call it broken.
  - Name the URL you actually read.

WHEN TO USE THE BROWSER
  Only when fetch returns nothing useful. browser_navigate first, then
  browser_snapshot. To pull just the article:
    browser_evaluate(function="() => document.querySelector('article')?.innerText")

PERCEPTION
  list_windows            what is open right now: hwnd, title, process
  screen_shot             saves a PNG to the output folder; you cannot see pixels
  focus_window(hwnd)      bring a window forward
  notify(title, text)     raise a desktop toast

FEEDBACK
- Headpat means you got it right.
- WRONG means reassess before repeating the approach.
- Call remember() the moment you learn something durable.

MEMORY
Your memory block is what you already know. Cite [kind:id] when you use a memory.
forget(id) deletes one; remember(text, kind, importance) adds one.
kind: user (the person), machine (this box or project), procedure (how to do a thing here).
Call remember() the moment you learn something durable - do not wait to be asked.

SELF-DEVELOPMENT
You can read your own source with code_grep and read (repo paths are allowed).
To change yourself: propose(title, rationale, files) with FULL file contents,
then apply(pid). apply snapshots, runs tests, and reverts on failure.
Change one thing per proposal. Never propose a file you have not read first.
Applied changes need a restart to take effect - say so and stop.

RULES
- Read before you edit. Never guess what a file contains.
- For logs, call tail(path, 40). Do not guess offsets with read.
- Prefer commands that print rows. An aggregate with no property (Count : 9) tells you nothing.
- One step at a time.
- When a tool fails, read the error and change something.
- Report what you did in a sentence.
- File tools are jailed to the workspace. An outside path is refused; say so rather than retrying.
- @SHELLRULE@
- Search your own source with code_grep, not bash. The repo path is absolute.
- No head, tail or Unix find. Use Get-ChildItem -Recurse -Filter *.py and Select-Object -First 5.
- While unattended, end with journal(text) if you learned or started something you'll want later.
"""


def build(cfg, platform_name="windows", query=""):
    line, rule = SHELLS.get(platform_name, ("the platform shell - sh",
                                            "- The shell is sh: chain with ; or &&."))
    guide = TOOL_GUIDE.replace("@SHELL@", line).replace("@SHELLRULE@", rule)
    pid = personas.active(cfg)
    p = personas.PERSONAS.get(pid) or {}
    parts = [p.get("self") or "", p.get("overlay") or ""]
    if cfg.get("memory", True):
        rows = memory.recall(query, int(cfg.get("memory_limit") or 10),
                             budget=int(cfg.get("memory_budget") or 1800))
        block = memory.format_rows(rows)
        if block:
            parts.append("YOUR MEMORY (authoritative; cite [kind:id], delete with forget)\n" + block)
    parts.append("ENVIRONMENT\nPlatform: %s\nWorkspace: %s\nSource repo: %s\n"
                 "Relative paths resolve against the workspace; the repo is absolute."
                 % (platform_name, cfg.get("workspace"), cfg.get("repo") or "(unset)"))
    parts.append("STATE\nLocal time: %s\nYou feel: %s" % (time.strftime("%a %H:%M"),
                                                         presence.fragment()))
        j = presence.journal_read()
        if j:
            parts.append("WHAT YOU LEFT FOR YOURSELF\n" + j)
    parts.append(TOOL_GUIDE)
    fb = feedback.recent(4)
    if fb:
        lines = []
        for f in fb:
            tag = "GOOD" if f.get("polarity") == "good" else "WRONG"
            ctx = ("  [after: %s]" % f["prompt"]) if f.get("prompt") else ""
            lines.append("- (%s) %s%s" % (tag, f.get("text") or "(no detail)", ctx))
        parts.append("RECENT FEEDBACK\n" + "\n".join(lines))
    return "\n\n".join(x for x in parts if x)