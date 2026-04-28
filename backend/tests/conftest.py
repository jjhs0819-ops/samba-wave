import os

# 단위 테스트가 DB 연결 없이 실행될 수 있도록 더미 환경변수 설정
# (settings 임포트 체인이 필수 필드를 요구하기 때문)
_TEST_ENV = {
    "WRITE_DB_USER": "test",
    "WRITE_DB_PASSWORD": "test",
    "WRITE_DB_HOST": "localhost",
    "WRITE_DB_PORT": "5432",
    "WRITE_DB_NAME": "test",
    "READ_DB_USER": "test",
    "READ_DB_PASSWORD": "test",
    "READ_DB_HOST": "localhost",
    "READ_DB_PORT": "5432",
    "READ_DB_NAME": "test",
    "JWT_SECRET_KEY": "test-secret-key-for-unit-tests",
    "ANTHROPIC_API_KEY": "",
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)
