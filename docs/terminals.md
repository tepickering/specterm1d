# Terminals

```{warning}
On iTerm2, every distinct inline image costs about a decoded bitmap of
resident memory for the life of the session — roughly 1.7 MB per redraw on
3.6.11 — and nothing the application can send releases it. specterm1d
therefore routes iTerm2 to a matplotlib window automatically. `--renderer
iterm2` overrides that, at the cost described below.
```

```{include} ../README.md
:start-after: "## Terminal support"
:end-before: "### Two-window mode"
```

## Two-window mode

```{include} ../README.md
:start-after: "### Two-window mode"
:end-before: "### Why iTerm2 gets a window"
```

## Why iTerm2 gets a window

```{include} ../README.md
:start-after: "### Why iTerm2 gets a window"
:end-before: "## Keys"
```
