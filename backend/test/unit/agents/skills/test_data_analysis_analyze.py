"""data-analysis 技能 analyze.py 脚本单元测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# 加载 analyze.py 作为模块
_SCRIPT_PATH = Path(__file__).resolve().parents[4] / "package" / "yuxi" / "agents" / "skills" / "buildin" / "data-analysis" / "scripts" / "analyze.py"

try:
    import duckdb  # noqa: F401
    import openpyxl  # noqa: F401

    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False

pytestmark = pytest.mark.skipif(not _HAS_DEPS, reason="duckdb and openpyxl required")


@pytest.fixture()
def analyze():
    """动态加载 analyze.py 模块。"""
    spec = importlib.util.spec_from_file_location("analyze", _SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # 阻止 argparse 解析 pytest 参数
    sys.modules["analyze"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("analyze", None)


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "test_data.csv"
    csv_file.write_text(
        "name,age,score,city\n"
        "Alice,30,95.5,Beijing\n"
        "Bob,25,88.0,Shanghai\n"
        "Charlie,35,92.3,Beijing\n"
        "Diana,28,,Shenzhen\n"
        "Eve,30,76.1,Beijing\n",
        encoding="utf-8",
    )
    return csv_file


@pytest.fixture()
def sample_excel(tmp_path: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["product", "quantity", "price"])
    ws.append(["Apple", 10, 5.0])
    ws.append(["Banana", 20, 3.0])
    ws.append(["Cherry", 5, 12.0])
    excel_file = tmp_path / "test_data.xlsx"
    wb.save(excel_file)
    return excel_file


# ── sanitize_table_name ──


class TestSanitizeTableName:
    def test_basic(self, analyze):
        assert analyze.sanitize_table_name("Orders") == "Orders"

    def test_special_chars(self, analyze):
        assert analyze.sanitize_table_name("My Sheet (1)") == "My_Sheet__1_"

    def test_digit_prefix(self, analyze):
        assert analyze.sanitize_table_name("2024_Sales") == "t_2024_Sales"

    def test_spaces(self, analyze):
        assert analyze.sanitize_table_name("hello world") == "hello_world"


# ── compute_files_hash ──


class TestComputeFilesHash:
    def test_same_content_same_hash(self, tmp_path: Path, analyze):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("hello", encoding="utf-8")
        assert analyze.compute_files_hash([str(f1)]) == analyze.compute_files_hash([str(f2)])

    def test_different_content_different_hash(self, tmp_path: Path, analyze):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("world", encoding="utf-8")
        assert analyze.compute_files_hash([str(f1)]) != analyze.compute_files_hash([str(f2)])

    def test_order_independent(self, tmp_path: Path, analyze):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("aaa", encoding="utf-8")
        f2.write_text("bbb", encoding="utf-8")
        assert analyze.compute_files_hash([str(f1), str(f2)]) == analyze.compute_files_hash([str(f2), str(f1)])


# ── load_csv ──


class TestLoadCsv:
    def test_load_single_csv(self, sample_csv, analyze):
        db_path = str(sample_csv.parent / "test.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        assert "test_data" in table_map
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_map["test_data"]}"').fetchone()[0]
        assert row_count == 5
        con.close()

    def test_load_csv_column_names(self, sample_csv, analyze):
        db_path = str(sample_csv.parent / "test2.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        columns = con.execute(f'DESCRIBE "{table_map["test_data"]}"').fetchall()
        col_names = [c[0] for c in columns]
        assert "name" in col_names
        assert "age" in col_names
        assert "score" in col_names
        con.close()


# ── load_excel ──


class TestLoadExcel:
    def test_load_excel_sheet(self, sample_excel, analyze):
        db_path = str(sample_excel.parent / "test.duckdb")
        con = duckdb.connect(db_path)
        con.execute("INSTALL spatial; LOAD spatial;")
        table_map: dict[str, str] = {}
        analyze._load_excel(con, str(sample_excel), table_map)
        assert "Orders" in table_map
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_map["Orders"]}"').fetchone()[0]
        assert row_count == 3
        con.close()


# ── action_inspect ──


class TestActionInspect:
    def test_inspect_output_contains_columns(self, sample_csv, analyze, capsys):
        db_path = str(sample_csv.parent / "inspect.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        analyze.action_inspect(con, table_map)
        captured = capsys.readouterr().out
        assert "name" in captured
        assert "age" in captured
        assert "Rows: 5" in captured
        con.close()


# ── action_query ──


class TestActionQuery:
    def test_simple_query(self, sample_csv, analyze, capsys):
        db_path = str(sample_csv.parent / "query.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        analyze.action_query(con, 'SELECT name, age FROM test_data WHERE age > 28', table_map)
        captured = capsys.readouterr().out
        assert "Alice" in captured
        assert "Charlie" in captured
        assert "Eve" in captured
        assert "Bob" not in captured  # Bob is 25
        con.close()

    def test_export_csv(self, sample_csv, tmp_path, analyze):
        db_path = str(sample_csv.parent / "export.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        output_file = str(tmp_path / "result.csv")
        analyze.action_query(con, "SELECT name, age FROM test_data LIMIT 2", table_map, output_file=output_file)
        content = Path(output_file).read_text(encoding="utf-8")
        assert "name" in content
        assert "age" in content
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 3  # header + 2 rows

    def test_export_json(self, sample_csv, tmp_path, analyze):
        db_path = str(sample_csv.parent / "export_json.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        output_file = str(tmp_path / "result.json")
        analyze.action_query(con, "SELECT name FROM test_data LIMIT 1", table_map, output_file=output_file)
        data = json.loads(Path(output_file).read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["name"] == "Alice"

    def test_export_markdown(self, sample_csv, tmp_path, analyze):
        db_path = str(sample_csv.parent / "export_md.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        output_file = str(tmp_path / "result.md")
        analyze.action_query(con, "SELECT name FROM test_data LIMIT 2", table_map, output_file=output_file)
        content = Path(output_file).read_text(encoding="utf-8")
        assert "| name |" in content
        assert "| --- |" in content


# ── action_summary ──


class TestActionSummary:
    def test_numeric_summary(self, sample_csv, analyze, capsys):
        db_path = str(sample_csv.parent / "summary.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        analyze.action_summary(con, "test_data", table_map)
        captured = capsys.readouterr().out
        assert "age" in captured
        assert "mean" in captured
        assert "min" in captured
        assert "max" in captured

    def test_text_summary(self, sample_csv, analyze, capsys):
        db_path = str(sample_csv.parent / "summary_text.duckdb")
        con = duckdb.connect(db_path)
        table_map: dict[str, str] = {}
        analyze._load_csv(con, str(sample_csv), table_map)
        analyze.action_summary(con, "test_data", table_map)
        captured = capsys.readouterr().out
        assert "city" in captured
        assert "unique" in captured or "top" in captured
