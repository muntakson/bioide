# VS Code / code-server UI Region Terms

The full map of Workbench terminology for VS Code / code-server UI regions.

## Layout diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Title Bar  (menus · window title · centered command box)              │
├───┬──────────────┬──────────────────────────────────┬─────────────────┤
│ A │              │  Tabs                              │                 │
│ c │              │──────────────────────────────────│  Secondary      │
│ t │   Side Bar   │  Breadcrumbs                       │  Side Bar       │
│ i │  (Primary)   │──────────────────────────────────│  (optional,     │
│ v │              │                          │M│      │   right edge)   │
│ i │  Explorer /  │        Editor Group      │i│      │                 │
│ t │  Search /    │      (files open here)   │n│      │                 │
│ y │  SCM /       │                          │i│      │                 │
│   │  Run·Debug / │       ← Gutter           │m│      │                 │
│ B │  Extensions  │                          │a│      │                 │
│ a │              │              Overview Ruler ↑│p│   │                 │
│ r │              │                          │ ││      │                 │
│   │              ├──────────────────────────┴─┴──────┤                 │
│   │              │  Panel                             │                 │
│   │              │  (Terminal · Problems · Output ·   │                 │
│   │              │   Debug Console)                   │                 │
├───┴──────────────┴────────────────────────────────────┴────────────────┤
│  Status Bar  (branch · errors/warnings · ln/col · language · encoding)  │
└──────────────────────────────────────────────────────────────────────┘

  Overlays float on top: Command Palette / Quick Open (top-center),
  Notifications (bottom-right), Hover / IntelliSense / Context Menu (at cursor).

  Everything together = the Workbench.
```

## Primary regions

| Term | Where it is / what it holds |
|------|------------|
| **Activity Bar** | Far-left vertical icon strip — switches Side Bar views (Explorer, Search, SCM, Run/Debug, Extensions). |
| **Side Bar** (Primary Side Bar) | Wide panel next to the Activity Bar — shows the file tree, search results, extension list, etc. |
| **Secondary Side Bar** | Optional panel on the **right** edge — you can drag views into it (e.g. to keep a second view open). |
| **Editor / Editor Group** | The central area where files open. Split it into multiple **Editor Groups** side by side. |
| **Panel** | The bottom area — **Terminal, Problems, Output, Debug Console**. Can be moved to the left/right. |
| **Status Bar** | Thin bar along the very bottom — branch, errors/warnings, line/column, language mode, encoding. |
| **Title Bar** | Top strip — menus, window title, and (in newer layouts) the centered command/search box. |
| **Menu Bar** | The **File / Edit / View …** menus (part of, or below, the Title Bar). |

## Editor sub-parts

| Term | What it is |
|------|------------|
| **Tabs** (Editor Tabs) | The row of open-file tabs at the top of an editor group. |
| **Breadcrumbs** | The clickable file/symbol path just under the tabs. |
| **Editor Toolbar / Editor Actions** | Icons at the top-right of an editor group (split, more actions). |
| **Minimap** | The zoomed-out code overview on the right edge of the editor. |
| **Gutter** | The narrow margin left of the code — line numbers, breakpoints, fold controls, SCM markers. |
| **Overview Ruler** | The thin colored strip inside the scrollbar showing errors, matches, changes. |
| **Peek View** | The inline popup for "Peek Definition / References." |

## Overlays and widgets

| Term | What it is |
|------|------------|
| **Command Palette** | The `Ctrl/Cmd+Shift+P` dropdown (a **Quick Input / Quick Pick** widget). |
| **Quick Open** | The `Ctrl/Cmd+P` file-jump box (same Quick Input widget). |
| **Notifications** | Toasts in the bottom-right corner. |
| **Hover** | The tooltip popup over symbols/errors. |
| **IntelliSense / Suggest Widget** | The autocomplete dropdown. |
| **Context Menu** | The right-click menu. |

## The umbrella term

The whole thing — everything above combined — is the **Workbench**. VS Code's own layout API
groups the big regions into "**Parts**": Activity Bar Part, Sidebar Part, Editor Part, Panel Part,
Status Bar Part, Title Bar Part.

> Note for the GHBIO code-server setup: the built-in Copilot/chat views normally live in the
> **Secondary Side Bar** or as a **Panel** view — relevant since `settings.json` disables them.
