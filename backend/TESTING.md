# Backend Testing Guide

**Last Updated**: 2025-11-03

This guide explains how to write and run tests for the backend services.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Running Tests](#running-tests)
3. [Writing Service Tests](#writing-service-tests)
4. [Test Data Factories](#test-data-factories)
5. [Mocking Strategies](#mocking-strategies)
6. [Coverage Guidelines](#coverage-guidelines)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest

# Run tests with coverage report
pytest --cov=backend --cov-report=html
open htmlcov/index.html  # View coverage report

# Run specific test file
pytest tests/unit/domain/user/test_service.py -v

# Run specific test method
pytest tests/unit/domain/user/test_service.py::TestUserService::test_is_admin_user -v
```

---

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Specific Test Directory

```bash
# All service tests
pytest tests/unit/domain/*/test_service.py

# Specific domain
pytest tests/unit/domain/artist/

# All unit tests
pytest tests/unit/
```

### Run with Coverage

```bash
# Terminal report
pytest --cov=backend --cov-report=term-missing

# HTML report (opens in browser)
pytest --cov=backend --cov-report=html
open htmlcov/index.html
```

### Run Failed Tests Only

```bash
# Re-run only failed tests from last run
pytest --lf

# Run failed tests first, then others
pytest --ff
```

### Verbose Output

```bash
# Show test names
pytest -v

# Show print statements
pytest -s

# Both
pytest -vs
```

---

## Writing Service Tests

### Basic Test Structure

```python
# tests/unit/domain/user/test_service.py
import pytest
from unittest.mock import AsyncMock, patch

from backend.domain.user.service import UserService
from backend.domain.user.model import User
from tests.factories import UserFactory


@pytest.mark.asyncio
class TestUserService:
    """Test suite for UserService."""

    @patch('backend.domain.user.service.UserRepository')
    async def test_is_admin_user_returns_true_for_admin(
        self,
        mock_user_repo_class,
        mock_session,
        mock_user_repository,
    ):
        """Test that is_admin_user returns True for admin users."""
        # Arrange: Configure mock to return our fixture
        mock_user_repo_class.return_value = mock_user_repository
        mock_user_repository.get_async.return_value = UserFactory.create_admin()

        # Create service (uses mocked repository automatically)
        service = UserService(mock_session)

        # Act
        result = await service.is_admin_user("user-1")

        # Assert
        assert result is True
        mock_user_repository.get_async.assert_called_once_with(id="user-1")
```

### Key Patterns

#### 1. Use @patch Decorator for Repository Mocking

**DO**:
```python
@patch('backend.domain.artist.service.ArtistRepository')
async def test_update_artist(mock_repo_class, mock_session, mock_artist_repository):
    mock_repo_class.return_value = mock_artist_repository
    service = ArtistService(mock_session)  # Auto-uses mock
```

**DON'T**:
```python
# ❌ Manual injection doesn't work properly
service = ArtistService(mock_session)
service._artist_repository = mock_artist_repository  # Too late!
```

#### 2. Patch at Import Location, Not Definition

**DO**:
```python
# Mock where it's IMPORTED (in the service module)
@patch('backend.domain.artwork.service.PDFGenerator')
```

**DON'T**:
```python
# ❌ Wrong: patches definition, not usage
@patch('backend.utils.pdf.PDFGenerator')
```

#### 3. Use AsyncMock for Async Methods

**DO**:
```python
mock_repo.get_async = AsyncMock(return_value=artist)
result = await service.get_artist(artist_id="123")
```

**DON'T**:
```python
# ❌ Regular Mock doesn't work with await
mock_repo.get_async = MagicMock(return_value=artist)
```

---

## Test Data Factories

Factories provide realistic test data with sensible defaults.

### Using Factories

```python
from tests.factories import ArtistFactory, UserFactory, ArtworkFactory

# Create with defaults
artist_dto = ArtistFactory.create_request_dto()
user = UserFactory.create_model()

# Override specific fields
artist_dto = ArtistFactory.create_request_dto(
    name_ko="커스텀 작가",
    host_name="custom-artist",
)

# Create admin user
admin = UserFactory.create_admin(email="admin@example.com")
```

### Available Factories

- `ArtistFactory`: `create_request_dto()`, `create_response_dto()`, `create_model()`
- `ArtworkFactory`: `create_request_dto()`, `create_response_dto()`, `create_model()`
- `ExhibitionFactory`: `create_info_dto()`
- `UserFactory`: `create_model()`, `create_admin()`

### Creating New Factories

```python
# tests/factories.py
class MyEntityFactory:
    @staticmethod
    def create_model(**overrides):
        defaults = {
            "id": "entity_123",
            "name": "Default Name",
            # ... all required fields with defaults
        }
        defaults.update(overrides)
        return MyEntity(**defaults)
```

---

## Mocking Strategies

### Mock Repository Methods

```python
# Configure return value
mock_artist_repository.get_async.return_value = artist

# Configure multiple calls with different return values
mock_artist_repository.get_async.side_effect = [artist1, artist2, None]

# Verify method was called
mock_artist_repository.get_async.assert_called_once_with(id="artist-1")

# Verify method was NOT called
mock_artist_repository.create_async.assert_not_called()
```

### Mock External Utilities

For module-level imports (PDFGenerator, S3 functions):

```python
@patch('backend.domain.artwork.service.PDFGenerator')
@patch('backend.domain.artwork.service.push_outputs')
@pytest.mark.asyncio
async def test_generate_pdf(mock_push, mock_pdf_class):
    # Configure PDF generator mock
    mock_pdf_instance = MagicMock()
    mock_pdf_instance.generate_portfolio_pdf = AsyncMock(
        return_value=b'fake pdf bytes'
    )
    mock_pdf_class.return_value = mock_pdf_instance

    # Configure S3 mock
    mock_push.return_value = ['https://s3.url/file.pdf']

    # Test service method
    service = ArtworkService(mock_session)
    result = await service.generate_portfolio_to_pdf(...)

    # Verify
    mock_pdf_instance.generate_portfolio_pdf.assert_called_once()
    mock_push.assert_called_once()
```

### Using Shared Fixtures

All domain tests have access to these fixtures (from `tests/unit/domain/conftest.py`):

- `mock_session`: Mock AsyncSession
- `mock_artist_repository`
- `mock_artwork_repository`
- `mock_exhibition_repository`
- `mock_user_repository`
- `mock_direct_message_repository`
- `mock_notification_repository`
- `mock_subscription_repository`

---

## Coverage Guidelines

### Target Coverage

- **Overall**: 80%+ for all service files
- **Simple Services** (User, Subscription): Aim for 90-100%
- **Complex Services** (Artist, Artwork): 80%+ acceptable

### Checking Coverage

```bash
# Run tests with coverage
pytest --cov=backend/domain --cov-report=term-missing

# Generate HTML report
pytest --cov=backend/domain --cov-report=html
open htmlcov/index.html
```

### Coverage Exclusions

These are automatically excluded (configured in `pyproject.toml`):

- `*/__init__.py`
- `*/tests/*`
- `if __name__ == "__main__":`
- `if TYPE_CHECKING:`
- `raise NotImplementedError`
- `def __repr__`

### What to Test

**DO Test**:
- ✅ Business logic (validation, calculations)
- ✅ Error handling (NotFoundError, ValueError)
- ✅ Edge cases (empty lists, None values)
- ✅ Method interactions (service → repository)

**DON'T Test**:
- ❌ Pydantic model validation (tested by Pydantic)
- ❌ SQLModel ORM behavior (tested by SQLModel)
- ❌ Simple getters/setters with no logic
- ❌ Third-party library behavior

---

## Troubleshooting

### Import Errors

**Problem**: `ModuleNotFoundError: No module named 'backend'`

**Solution**: Make sure you're in the backend virtual environment:
```bash
cd backend
source .venv/bin/activate
uv sync --group dev
```

### AsyncMock Issues

**Problem**: `TypeError: object MagicMock can't be used in 'await' expression`

**Solution**: Use `AsyncMock` for async methods:
```python
# ✅ Correct
mock_repo.get_async = AsyncMock(return_value=value)

# ❌ Wrong
mock_repo.get_async = MagicMock(return_value=value)
```

### Patch Not Working

**Problem**: Mock not being used in service

**Solution**: Patch where it's imported, not where it's defined:
```python
# ✅ Correct: Patch in service module
@patch('backend.domain.artist.service.ArtistRepository')

# ❌ Wrong: Patches definition
@patch('backend.domain.artist.repository.ArtistRepository')
```

### Fixture Not Found

**Problem**: `fixture 'mock_artist_repository' not found`

**Solution**: Make sure you're in the correct test directory structure:
```
tests/
└── unit/
    └── domain/
        ├── conftest.py        # ← Fixtures defined here
        └── artist/
            └── test_service.py  # ← Can use fixtures
```

### Coverage Too Low

**Problem**: Coverage is below 80%

**Solution**:
1. Check which lines are not covered:
   ```bash
   pytest --cov=backend/domain --cov-report=term-missing
   ```
2. Add tests for uncovered lines
3. Or mark code as excluded if it's truly untestable:
   ```python
   if condition:  # pragma: no cover
       raise NotImplementedError("Future feature")
   ```

---

## Best Practices

1. **One Test Per Behavior**: Each test should verify one specific behavior
2. **Arrange-Act-Assert**: Structure tests with clear setup, execution, verification
3. **Descriptive Names**: Test names should describe what they test
   - ✅ `test_update_artist_raises_error_when_host_name_exists`
   - ❌ `test_update_artist_2`
4. **Use Factories**: Don't create test data manually
5. **Async Everything**: All service methods are async, tests must be too
6. **Clean Mocks**: Reset mocks between tests (pytest does this automatically with fixtures)

---

## Examples

See these files for examples:
- `tests/test_factories.py` - Factory usage examples
- `tests/unit/domain/test_fixtures.py` - Fixture usage examples
- `dev/active/backend-service-testing/backend-service-testing-context.md` - Detailed patterns

---

**Questions?** Check the plan at `dev/active/backend-service-testing/` or ask the team!
