import asyncio
import asyncpg
from backend.core.config import settings


async def main():
  c = await asyncpg.connect(
    host=settings.write_db_host, port=settings.write_db_port,
    user=settings.write_db_user, password=settings.write_db_password,
    database=settings.write_db_name, ssl=False,
  )
  for tbl in ('samba_monitor_event', 'samba_collected_product'):
    print(f'ANALYZE {tbl} ...', flush=True)
    await c.execute(f'ANALYZE {tbl}')
    print(f'  done')
  await c.close()


asyncio.run(main())
