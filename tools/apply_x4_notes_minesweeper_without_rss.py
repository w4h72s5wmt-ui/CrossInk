import ast
from pathlib import Path

# Build 244's Notes/Minesweeper consolidation also used to bootstrap the RSS app.
# RSS is now stored directly in its final source form, so execute the exact same
# consolidation while filtering only the historical RSS sub-patches and their
# obsolete post-patch assertions. Notes/Minesweeper behaviour is untouched.
source_path = Path("tools/apply_x4_notes_minesweeper_consolidated.py")
source = source_path.read_text()
tree = ast.parse(source, filename=str(source_path))


class RemoveHistoricalRssSteps(ast.NodeTransformer):
    def visit_Assign(self, node):
        self.generic_visit(node)
        if any(isinstance(target, ast.Name) and target.id == "PATCHES" for target in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                node.value.elts = [
                    elt for elt in node.value.elts
                    if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            and "apply_x4_rss_" in elt.value)
                ]
        return node

    def visit_Expr(self, node):
        self.generic_visit(node)
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in ("require", "reject"):
            if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                if "/Rss" in call.args[0].value:
                    return None
        return node


tree = RemoveHistoricalRssSteps().visit(tree)
ast.fix_missing_locations(tree)
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(tree, str(source_path), "exec"), namespace, namespace)
