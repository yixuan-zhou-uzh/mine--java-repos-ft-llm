from tree_sitter import Language, Parser

# Load the compiled Java grammar
JAVA_LANG = Language(
    "/home/yixuan/Documents/master/processor/tree-sitter-langs/build/my-languages.so",
    "java"
)

# Initialize parser
parser = Parser()
parser.set_language(JAVA_LANG)

# Sample Java code
code = b"""
/**
 * Example class comment
 */
public class TestClass {
    // inline comment
    public void foo() {}
}
"""

tree = parser.parse(code)
root_node = tree.root_node

print("Root node type:", root_node.type)
print("Children of root node:")
for child in root_node.children:
    print("-", child.type, child.start_point, child.end_point)
