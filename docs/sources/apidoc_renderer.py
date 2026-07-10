"""Custom autodoc2 renderer for the top-level API page.

Gives the generated ``bibdeskparser`` package page a generic
"Package API" title, with the module name (linked) and the first
line of its docstring as a tagline underneath, instead of autodoc2's
default ``# {py:mod}`bibdeskparser``` title.
"""

from autodoc2.render.myst_ import MystRenderer
from autodoc2.utils import ItemData


class Renderer(MystRenderer):
    """MyST renderer with a custom title for the top-level package.

    Everything below the title/docstring header (subpackages,
    submodules, package contents) is produced by
    `MystRenderer.render_package`; only that header is replaced here,
    so this must be kept in sync with any changes to autodoc2's
    `render_package` beyond its first few yields.
    """

    def render_package(self, item: ItemData):
        full_name = item["full_name"]
        if "." in full_name:
            # Not the top-level package: keep autodoc2's normal title.
            yield from super().render_package(item)
            return

        if self.standalone and self.is_hidden(item):
            yield from ["---", "orphan: true", "---", ""]

        yield "# Package API"
        yield ""

        doc = item.get("doc", "")
        summary, _, rest = doc.partition("\n\n")
        if summary.strip():
            yield f"{{py:mod}}`{full_name}` – {summary.strip()}"
        else:
            yield f"{{py:mod}}`{full_name}`"
        yield ""

        yield f"```{{py:module}} {full_name}"
        if self.no_index(item):
            yield ":noindex:"
        if self.is_module_deprecated(item):
            yield ":deprecated:"
        yield from ["```", ""]

        if self.show_docstring(item) and rest.strip():
            yield rest
            yield ""

        yield from self._render_package_body(item)

    def _render_package_body(self, item: ItemData):
        """Subpackages/Submodules/Package Contents.

        Copied from `MystRenderer.render_package`.
        """
        visible_subpackages = [
            i["full_name"] for i in self.get_children(item, {"package"})
        ]
        if visible_subpackages:
            yield from [
                "## Subpackages",
                "",
                "```{toctree}",
                ":titlesonly:",
                ":maxdepth: 3",
                "",
            ]
            for name in visible_subpackages:
                yield name
            yield "```"
            yield ""

        visible_submodules = [
            i["full_name"] for i in self.get_children(item, {"module"})
        ]
        if visible_submodules:
            yield from [
                "## Submodules",
                "",
                "```{toctree}",
                ":titlesonly:",
                ":maxdepth: 1",
                "",
            ]
            for name in visible_submodules:
                yield name
            yield "```"
            yield ""

        visible_children = [
            i["full_name"]
            for i in self.get_children(item)
            if i["type"] not in ("package", "module")
        ]
        if not visible_children:
            return

        yield f"## {item['type'].capitalize()} Contents"
        yield ""

        if self.show_module_summary(item):
            for heading, types in [
                ("Classes", {"class"}),
                ("Functions", {"function"}),
                ("Data", {"data"}),
                ("External", {"external"}),
            ]:
                visible_items = list(self.get_children(item, types))
                if visible_items:
                    yield from [f"### {heading}", ""]
                    yield from self.generate_summary(
                        visible_items,
                        alias={
                            i["full_name"]: i["full_name"].split(".")[-1]
                            for i in visible_items
                        },
                    )
                    yield ""

            yield from ["### API", ""]
            for name in visible_children:
                yield from self.render_item(name)
