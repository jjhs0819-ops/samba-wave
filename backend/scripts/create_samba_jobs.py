import asyncio
import asyncpg


async def create_table():
    conn = await asyncpg.connect(
        host="34.64.205.34",
        port=5432,
        user="samba-user",
        password="SambaWave2024x",
        database="samba-wave",
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS samba_jobs (
            id VARCHAR NOT NULL PRIMARY KEY,
            tenant_id VARCHAR,
            job_type VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            payload JSON,
            result JSON,
            progress INTEGER,
            total INTEGER,
            current INTEGER,
            error TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS ix_samba_jobs_job_type ON samba_jobs (job_type);
        CREATE INDEX IF NOT EXISTS ix_samba_jobs_status ON samba_jobs (status);
        CREATE INDEX IF NOT EXISTS ix_samba_jobs_tenant_id ON samba_jobs (tenant_id);
    """)
    await conn.close()
    print("samba_jobs 테이블 생성 완료")


asyncio.run(create_table())
