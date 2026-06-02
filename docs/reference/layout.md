# Layout

`golit.layout` arranges the reactive view fragments into a page. **References** (`View`, `Control`, `Controls`) point at nodes by id; **containers** (`Row`, `Stack`, `Grid`, `Tabs`, `Section`, `Sidebar`) nest. Assign a tree to `app.layout`. See the [Page layout](../tutorial/layout.md) tutorial.

::: golit.layout
    options:
      members_order: source
      show_root_heading: false
      show_root_toc_entry: false
      filters:
        - "!^_"
        - "!^render_layout$"
