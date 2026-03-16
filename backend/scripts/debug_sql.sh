#!/bin/bash

# {backend/debug_sql.sh}

# Script to run the backend with SQL query debugging enabled

echo "Starting backend with SQL query logging enabled..."
echo "All SQL queries will be logged to the console."
echo ""

set -e

# Default to development if APP_ENV is not set
if [ -z "$APP_ENV" ]; then
  APP_ENV="development"
  export $(cat .env | xargs) 2>/dev/null
fi

# Set the SQL_DEBUG environment variable to enable query logging
export SQL_DEBUG=true

# Run the backend with uvicorn (adjust the command as needed for your setup)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 28080

# Alternative: If you're using a different command to start your server, replace the above line.
# For example:
# python -m backend.main
# or
# gunicorn backend.main:app
