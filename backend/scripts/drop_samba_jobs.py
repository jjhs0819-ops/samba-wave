import asyncio
import asyncpg


async def drop():
    conn = await asyncpg.connect(
        host='34.64.205.34', port=5432,
        user='samba-user', password='SambaWave2024x',
        database='samba-wave'
    )
    await conn.execute('DROP TABLE IF EXISTS samba_jobs CASCADE')
    await conn.close()
    print('완료')


asyncio.run(drop())
