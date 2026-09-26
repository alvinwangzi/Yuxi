"""初始化内置技能市场条目"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 添加 package 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "package"))


async def seed_builtin_market_entries():
    """将现有内置技能同步到市场条目"""
    from sqlalchemy import text
    from yuxi.storage.postgres.manager import pg_manager

    pg_manager.initialize()

    async with pg_manager.get_async_session_context() as session:
        # 获取所有内置技能
        result = await session.execute(
            text("SELECT id, slug, name, description, version, content_hash FROM skills WHERE source_type = 'builtin'")
        )
        builtin_skills = result.fetchall()

        print(f"Found {len(builtin_skills)} builtin skills")

        for skill in builtin_skills:
            skill_id, slug, name, description, version, content_hash = skill

            market_slug = f"builtin-{slug}"

            # 检查是否已存在市场条目
            check = await session.execute(
                text("SELECT id FROM skill_market_entries WHERE slug = :slug"),
                {"slug": market_slug}
            )
            existing = check.fetchone()

            if existing:
                print(f"  Skip {slug} (already exists)")
                continue

            # 创建市场条目
            entry_result = await session.execute(
                text("""
                    INSERT INTO skill_market_entries
                    (slug, title, description, source_type, status, install_count)
                    VALUES (:slug, :title, :description, 'builtin', 'approved', 0)
                    RETURNING id
                """),
                {
                    "slug": market_slug,
                    "title": name,
                    "description": description or name,
                }
            )
            entry_id = entry_result.scalar()

            # 创建首个版本
            snapshot = json.dumps({
                "skill_id": skill_id,
                "content_hash": content_hash,
                "source": "builtin",
                "tool_dependencies": [],
                "mcp_dependencies": [],
                "skill_dependencies": [],
            })

            await session.execute(
                text("""
                    INSERT INTO skill_market_versions
                    (entry_id, version, release_notes, content_snapshot, change_type, submitted_by, is_latest)
                    VALUES (:entry_id, :version, '初始版本', CAST(:snapshot AS jsonb), 'minor', 'system', TRUE)
                """),
                {
                    "entry_id": entry_id,
                    "version": version or "1.0.0",
                    "snapshot": snapshot,
                }
            )

            print(f"  Created market entry for {slug} (id={entry_id})")

        await session.commit()

    print("Done")


if __name__ == "__main__":
    asyncio.run(seed_builtin_market_entries())
