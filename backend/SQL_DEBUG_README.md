# SQL Query Debugging

This backend now supports SQL query logging for debugging purposes. When enabled, all SQL queries executed by SQLAlchemy will be logged to the console with their parameters.

## How to Enable SQL Query Logging

### Method 1: Using Environment Variable

Set the `SQL_DEBUG` environment variable to `true` before starting the server:

```bash
export SQL_DEBUG=true
uvicorn backend.main:app --reload
```

### Method 2: Using the Debug Script

Run the provided debug script:

```bash
cd backend
./debug_sql.sh
```

### Method 3: In Docker or Docker Compose

Add the environment variable to your Docker configuration:

```yaml
environment:
  - SQL_DEBUG=true
```

## What Gets Logged

When SQL debugging is enabled, you'll see:

1. **Raw SQL queries** - The actual SQL statements being executed
2. **Query parameters** - The values being passed to parameterized queries
3. **Connection pool activity** - Connection checkout/checkin events
4. **Transaction boundaries** - BEGIN, COMMIT, and ROLLBACK statements

## Example Output

```
INFO:sqlalchemy.engine.Engine:SELECT product.id, product.title, product.price
FROM product
WHERE product.site_id = %(site_id_1)s
LIMIT %(param_1)s
INFO:sqlalchemy.engine.Engine:[generated in 0.00034s] {'site_id_1': UUID('8b497d88-decd-46b0-8674-16de3f3674c4'), 'param_1': 20}
```

## Performance Note

⚠️ **WARNING**: SQL query logging significantly impacts performance and generates verbose output. Only use this in development/debugging scenarios, never in production.

## Disabling SQL Query Logging

To disable SQL query logging, either:
- Unset the environment variable: `unset SQL_DEBUG`
- Set it to false: `export SQL_DEBUG=false`
- Simply don't set it (default is disabled)

## Troubleshooting

If you're not seeing SQL queries:
1. Ensure the environment variable is set correctly
2. Check that you're looking at the correct log output (stdout/stderr)
3. Verify that the backend is actually executing database queries
4. Make sure you've restarted the server after setting the environment variable
