-- 为定时任务表添加工作流支持
-- 执行方式: docker compose exec postgres psql -U yuxi -d yuxi -c "$(cat scripts/migrations/add_workflow_to_scheduled_tasks.sql)"

-- 为 scheduled_agent_jobs 表添加新字段
ALTER TABLE scheduled_agent_jobs 
ADD COLUMN IF NOT EXISTS target_type VARCHAR(16) NOT NULL DEFAULT 'agent',
ADD COLUMN IF NOT EXISTS workflow_id INTEGER;

-- 为 scheduled_agent_jobs 添加外键约束
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'fk_scheduled_agent_jobs_workflow_id'
    ) THEN
        ALTER TABLE scheduled_agent_jobs
        ADD CONSTRAINT fk_scheduled_agent_jobs_workflow_id
        FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE SET NULL;
    END IF;
END $$;

-- 为 scheduled_agent_jobs 添加检查约束
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'ck_scheduled_agent_jobs_target_type'
    ) THEN
        ALTER TABLE scheduled_agent_jobs
        ADD CONSTRAINT ck_scheduled_agent_jobs_target_type
        CHECK (target_type IN ('agent', 'workflow'));
    END IF;
END $$;

-- 为 scheduled_agent_jobs 添加索引
CREATE INDEX IF NOT EXISTS ix_scheduled_agent_jobs_workflow_id 
ON scheduled_agent_jobs(workflow_id);

-- 为 scheduled_agent_runs 表添加新字段
ALTER TABLE scheduled_agent_runs 
ADD COLUMN IF NOT EXISTS target_type VARCHAR(16) NOT NULL DEFAULT 'agent',
ADD COLUMN IF NOT EXISTS workflow_id INTEGER;

-- 将 agent_slug 和 prompt 字段改为可空（scheduled_agent_jobs）
ALTER TABLE scheduled_agent_jobs 
ALTER COLUMN agent_slug DROP NOT NULL,
ALTER COLUMN prompt DROP NOT NULL;

-- 将 agent_slug 和 prompt 字段改为可空（scheduled_agent_runs）
ALTER TABLE scheduled_agent_runs 
ALTER COLUMN agent_slug DROP NOT NULL,
ALTER COLUMN prompt DROP NOT NULL;
