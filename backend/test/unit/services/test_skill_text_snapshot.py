"""内置技能文本快照保留真实包内资源。"""

from yuxi.services.skills.package import read_skill_text_snapshot


def test_snapshot_preserves_nested_scripts_and_templates(tmp_path):
    """不同脚本类型与嵌套模板都进入快照。"""
    files = {
        "SKILL.md": "skill",
        "scripts/run.sh": "shell",
        "scripts/nested/render.mjs": "js",
        "project/scripts/build.py": "python",
        "templates/page.html": "html",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    snapshot = read_skill_text_snapshot(tmp_path)
    assert snapshot == {
        "skill_md": "skill",
        "scripts": {"run.sh": "shell", "nested/render.mjs": "js"},
        "files": {"project/scripts/build.py": "python", "templates/page.html": "html"},
    }
