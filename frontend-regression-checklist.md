# Frontend Regression Checklist

- Tree dup-only deep scroll:
  - host `brians-m2prombp`
  - `Only dups` on
  - `Min size = 100 MB`
  - scroll/load more deeply
  - confirm non-dup files do not leak into the tree

- Tree directory dup badge correctness:
  - verify `X uniq dup hashes` respects selected hosts, category filters, and `Min size`
  - click the badge and confirm overlay results match the badge claim

- File overlay behavior:
  - click a file row
  - confirm overlay opens cleanly
  - confirm Back restores the prior tree context

- Hash-search bypass behavior:
  - run a hash search for a known below-threshold file
  - confirm results still appear even when `Min size` or category filters would otherwise hide them

- List category multi-select:
  - switch to List view
  - select multiple categories without the menu collapsing to a single visible option
  - confirm multiple selected categories filter correctly

- Reset behavior:
  - apply host/filter/view changes
  - click Reset
  - confirm the page returns to fresh-load behavior:
    - Tree view
    - filters cleared
    - browser-matching host selected if present, otherwise all hosts selected

- Subtree duplicate overlay behavior:
  - click a directory `X uniq dup hashes`
  - from that overlay, click `Y extra copies`
  - confirm context results appear
  - confirm subtree rows are blue-highlighted and other duplicate rows remain yellow
