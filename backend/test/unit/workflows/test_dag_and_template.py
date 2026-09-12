"""工作流 DAG 引擎单元测试。"""

import pytest

from yuxi.workflows.dag import (
    WorkflowCycleError,
    WorkflowDefinitionError,
    build_dag,
    validate_definition,
)
from yuxi.workflows.template import (
    evaluate_condition,
    extract_variable_refs,
    resolve_template,
)


class TestDAGBuild:
    """DAG 构建测试。"""

    def test_single_step_no_deps(self):
        """单步骤无依赖在第一层。"""
        definition = {
            "steps": [
                {"id": "step1", "type": "llm", "name": "Step 1"},
            ]
        }
        layers = build_dag(definition)
        assert len(layers) == 1
        assert [n.id for n in layers[0].nodes] == ["step1"]

    def test_linear_chain(self):
        """线性链 A -> B -> C 分三层。"""
        definition = {
            "steps": [
                {"id": "a", "type": "llm", "name": "A"},
                {"id": "b", "type": "tool", "name": "B", "depends_on": ["a"]},
                {"id": "c", "type": "output", "name": "C", "depends_on": ["b"]},
            ]
        }
        layers = build_dag(definition)
        assert len(layers) == 3
        assert [n.id for n in layers[0].nodes] == ["a"]
        assert [n.id for n in layers[1].nodes] == ["b"]
        assert [n.id for n in layers[2].nodes] == ["c"]

    def test_parallel_steps(self):
        """并行步骤在同一层。"""
        definition = {
            "steps": [
                {"id": "start", "type": "llm", "name": "Start"},
                {"id": "branch_a", "type": "tool", "name": "Branch A", "depends_on": ["start"]},
                {"id": "branch_b", "type": "tool", "name": "Branch B", "depends_on": ["start"]},
                {"id": "branch_c", "type": "tool", "name": "Branch C", "depends_on": ["start"]},
                {"id": "end", "type": "output", "name": "End", "depends_on": ["branch_a", "branch_b", "branch_c"]},
            ]
        }
        layers = build_dag(definition)
        assert len(layers) == 3
        assert [n.id for n in layers[0].nodes] == ["start"]
        assert {n.id for n in layers[1].nodes} == {"branch_a", "branch_b", "branch_c"}
        assert [n.id for n in layers[2].nodes] == ["end"]

    def test_diamond_pattern(self):
        """菱形依赖 A -> B,C -> D。"""
        definition = {
            "steps": [
                {"id": "a", "type": "llm", "name": "A"},
                {"id": "b", "type": "tool", "name": "B", "depends_on": ["a"]},
                {"id": "c", "type": "tool", "name": "C", "depends_on": ["a"]},
                {"id": "d", "type": "output", "name": "D", "depends_on": ["b", "c"]},
            ]
        }
        layers = build_dag(definition)
        assert len(layers) == 3
        assert [n.id for n in layers[0].nodes] == ["a"]
        assert {n.id for n in layers[1].nodes} == {"b", "c"}
        assert [n.id for n in layers[2].nodes] == ["d"]


class TestCycleDetection:
    """成环检测测试。"""

    def test_direct_cycle(self):
        """直接循环 A -> B -> A。"""
        definition = {
            "steps": [
                {"id": "a", "type": "llm", "name": "A", "depends_on": ["b"]},
                {"id": "b", "type": "tool", "name": "B", "depends_on": ["a"]},
            ]
        }
        with pytest.raises(WorkflowCycleError):
            build_dag(definition)

    def test_indirect_cycle(self):
        """间接循环 A -> B -> C -> A。"""
        definition = {
            "steps": [
                {"id": "a", "type": "llm", "name": "A", "depends_on": ["c"]},
                {"id": "b", "type": "tool", "name": "B", "depends_on": ["a"]},
                {"id": "c", "type": "output", "name": "C", "depends_on": ["b"]},
            ]
        }
        with pytest.raises(WorkflowCycleError):
            build_dag(definition)

    def test_self_reference(self):
        """自引用 A -> A。"""
        definition = {
            "steps": [
                {"id": "a", "type": "llm", "name": "A", "depends_on": ["a"]},
            ]
        }
        with pytest.raises(WorkflowCycleError):
            build_dag(definition)


class TestValidateDefinition:
    """定义校验测试。"""

    def test_missing_steps(self):
        """缺少 steps 字段报错。"""
        errors = validate_definition({})
        assert any("steps" in e for e in errors)

    def test_empty_steps_invalid(self):
        """空 steps 列表无效（至少需要一个步骤）。"""
        errors = validate_definition({"steps": []})
        assert len(errors) > 0

    def test_missing_step_id(self):
        """步骤缺少 id 报错。"""
        definition = {
            "steps": [
                {"type": "llm", "name": "No ID"},
            ]
        }
        errors = validate_definition(definition)
        assert any("id" in e for e in errors)

    def test_invalid_step_type(self):
        """无效步骤类型报错。"""
        definition = {
            "steps": [
                {"id": "step1", "type": "invalid_type", "name": "Bad Type"},
            ]
        }
        errors = validate_definition(definition)
        assert any("type" in e for e in errors)

    def test_duplicate_step_ids(self):
        """重复步骤 ID 报错。"""
        definition = {
            "steps": [
                {"id": "step1", "type": "llm", "name": "First"},
                {"id": "step1", "type": "tool", "name": "Duplicate"},
            ]
        }
        errors = validate_definition(definition)
        assert any("重复" in e or "duplicate" in e.lower() for e in errors)

    def test_missing_dependency(self):
        """引用不存在的依赖报错。"""
        definition = {
            "steps": [
                {"id": "step1", "type": "llm", "name": "Step 1", "depends_on": ["nonexistent"]},
            ]
        }
        errors = validate_definition(definition)
        assert any("依赖" in e or "depend" in e.lower() for e in errors)


class TestLoopIgnoredInDAG:
    """循环字段在 DAG 构建中被忽略。"""

    def test_loop_back_to_ignored(self):
        """loop.back_to 不参与建边。"""
        definition = {
            "steps": [
                {"id": "draft", "type": "llm", "name": "Draft"},
                {
                    "id": "review",
                    "type": "llm",
                    "name": "Review",
                    "depends_on": ["draft"],
                    "loop": {
                        "back_to": "draft",
                        "max_iterations": 3,
                        "exit_condition": "{{result}} contains approved",
                    },
                },
            ]
        }
        # loop.back_to 不应导致成环
        layers = build_dag(definition)
        assert len(layers) == 2
        assert [n.id for n in layers[0].nodes] == ["draft"]
        assert [n.id for n in layers[1].nodes] == ["review"]


class TestTemplateResolution:
    """变量模板解析测试。"""

    def test_simple_variable(self):
        """简单变量替换。"""
        result = resolve_template("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_variables(self):
        """多个变量替换。"""
        result = resolve_template(
            "{{greeting}}, {{name}}!",
            {"greeting": "Hi", "name": "Alice"},
        )
        assert result == "Hi, Alice!"

    def test_nested_path(self):
        """嵌套路径访问。"""
        context = {"user": {"name": "Bob", "age": 30}}
        result = resolve_template("User: {{user.name}}, Age: {{user.age}}", context)
        assert result == "User: Bob, Age: 30"

    def test_missing_variable_empty(self):
        """缺失变量替换为空字符串。"""
        result = resolve_template("Hello {{name}}!", {})
        assert result == "Hello !"

    def test_numeric_value(self):
        """数值类型转换。"""
        result = resolve_template("Count: {{count}}", {"count": 42})
        assert result == "Count: 42"

    def test_dict_passthrough(self):
        """字典类型直接返回。"""
        data = {"key": "value"}
        result = resolve_template(data, {})
        assert result == data

    def test_list_passthrough(self):
        """列表类型直接返回。"""
        data = [1, 2, 3]
        result = resolve_template(data, {})
        assert result == data

    def test_whole_variable_preserves_type(self):
        """整个字符串是变量引用时保留原始类型。"""
        result = resolve_template("{{data}}", {"data": {"nested": "value"}})
        assert result == {"nested": "value"}


class TestConditionEvaluation:
    """条件表达式求值测试。"""

    def test_contains_true(self):
        """contains 条件为真。"""
        assert evaluate_condition("{{status}} contains approved", {"status": "approved"}) is True

    def test_contains_false(self):
        """contains 条件为假。"""
        assert evaluate_condition("{{status}} contains approved", {"status": "pending"}) is False

    def test_equals(self):
        """等于条件。"""
        assert evaluate_condition("{{count}} == 10", {"count": 10}) is True
        assert evaluate_condition("{{count}} == 5", {"count": 10}) is False

    def test_greater_than(self):
        """大于条件。"""
        assert evaluate_condition("{{score}} > 60", {"score": 80}) is True
        assert evaluate_condition("{{score}} > 60", {"score": 40}) is False

    def test_less_than(self):
        """小于条件。"""
        assert evaluate_condition("{{score}} < 60", {"score": 40}) is True
        assert evaluate_condition("{{score}} < 60", {"score": 80}) is False

    def test_truthy_check(self):
        """真值检查。"""
        assert evaluate_condition("{{flag}}", {"flag": True}) is True
        assert evaluate_condition("{{flag}}", {"flag": False}) is False
        assert evaluate_condition("{{flag}}", {"flag": "yes"}) is True
        assert evaluate_condition("{{flag}}", {"flag": ""}) is False


class TestVariableExtraction:
    """变量引用提取测试。"""

    def test_single_variable(self):
        """提取单个变量。"""
        refs = extract_variable_refs("Hello {{name}}!")
        assert refs == {"name"}

    def test_multiple_variables(self):
        """提取多个变量。"""
        refs = extract_variable_refs("{{greeting}}, {{name}}! Your score is {{score}}.")
        assert refs == {"greeting", "name", "score"}

    def test_nested_path(self):
        """提取嵌套路径变量。"""
        refs = extract_variable_refs("User: {{user.name}}, Age: {{user.age}}")
        assert refs == {"user.name", "user.age"}

    def test_no_variables(self):
        """无变量返回空集合。"""
        refs = extract_variable_refs("No variables here")
        assert refs == set()

    def test_duplicate_variables(self):
        """重复变量去重。"""
        refs = extract_variable_refs("{{name}} and {{name}} again")
        assert refs == {"name"}
