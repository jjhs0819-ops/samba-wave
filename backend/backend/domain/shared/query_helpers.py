"""
Query building helpers for type-safe repository operations.

This module provides utilities for:
- Type-safe locale-based field selection
- Standardized search pattern building
- Common query filtering patterns
"""

from typing import TYPE_CHECKING, Literal, Optional

from sqlalchemy import ColumnElement, func, or_
from sqlmodel import SQLModel

if TYPE_CHECKING:
    from sqlmodel.sql.expression import Select

# Type alias for supported locales
LocaleCode = Literal["ko", "en"]


class LocaleFieldSelector:
    """
    Type-safe locale field selection helper.

    Eliminates Union type issues from conditional field selection by
    providing a centralized, type-safe approach to locale-based field access.

    Example:
        >>> # Before (causes type errors)
        >>> if locale == "ko":
        >>>     name_field = Model.name_ko  # Union[Column, None]
        >>> else:
        >>>     name_field = Model.name_en  # Union[Column, None]
        >>> # mypy error: Union type not narrowed

        >>> # After (type-safe)
        >>> name_field = LocaleFieldSelector.select_field(Model, "name", locale)
        >>> # Returns: ColumnElement[Optional[str]]
    """

    @staticmethod
    def select_field(
        model: type[SQLModel], field_prefix: str, locale: LocaleCode
    ) -> ColumnElement[Optional[str]]:
        """
        Select locale-specific field with type safety.

        Args:
            model: SQLModel class (e.g., Artist, Artwork)
            field_prefix: Field prefix without locale suffix (e.g., "name", "material")
            locale: Language code ("ko" or "en")

        Returns:
            Column element for query building

        Raises:
            ValueError: If model doesn't have the specified field

        Example:
            >>> name_col = LocaleFieldSelector.select_field(Model, "name", "ko")
            >>> statement = select(Model).where(name_col.ilike("%test%"))
        """
        field_name = f"{field_prefix}_{locale}"

        if not hasattr(model, field_name):
            raise ValueError(
                f"Model {model.__name__} does not have field '{field_name}'. "
                f"Available fields: {', '.join(dir(model))}"
            )

        # Type assertion: we know this returns a Column
        column: ColumnElement[Optional[str]] = getattr(model, field_name)
        return column

    @staticmethod
    def select_multiple_fields(
        model: type[SQLModel], field_prefixes: list[str], locale: LocaleCode
    ) -> dict[str, ColumnElement[Optional[str]]]:
        """
        Select multiple locale-specific fields at once.

        Args:
            model: SQLModel class
            field_prefixes: List of field prefixes
            locale: Language code

        Returns:
            Dictionary mapping field_prefix to column element

        Example:
            >>> fields = LocaleFieldSelector.select_multiple_fields(
            ...     Model, ["name", "bio"], "ko"
            ... )
            >>> # fields = {"name": Model.name_ko, "bio": Model.bio_ko}
        """
        return {
            prefix: LocaleFieldSelector.select_field(model, prefix, locale)
            for prefix in field_prefixes
        }

    @staticmethod
    def get_field_name(field_prefix: str, locale: LocaleCode) -> str:
        """
        Get full field name for a locale prefix.

        Args:
            field_prefix: Field prefix without locale
            locale: Language code

        Returns:
            Full field name with locale suffix

        Example:
            >>> LocaleFieldSelector.get_field_name("name", "ko")
            'name_ko'
        """
        return f"{field_prefix}_{locale}"


class SearchPatternBuilder:
    """
    Build search patterns based on query length.

    Handles the difference between short queries (1-2 chars) and long queries (3+ chars):
    - Short queries: Use ILIKE only (trigram similarity poor with short strings)
    - Long queries: Use ILIKE + trigram similarity for fuzzy matching

    This standardizes search behavior across all repositories and eliminates
    duplicated short/long query logic.
    """

    # Configuration constants
    SHORT_QUERY_THRESHOLD = 2
    SIMILARITY_THRESHOLD = 0.1

    @staticmethod
    def build_search_condition(
        column: ColumnElement[Optional[str]],
        query: str,
        use_trigram_similarity: bool = True,
    ) -> ColumnElement[bool]:
        """
        Build search condition with appropriate pattern matching.

        Args:
            column: Column to search (from LocaleFieldSelector)
            query: Search query string
            use_trigram_similarity: Enable trigram for long queries (default: True)

        Returns:
            SQLAlchemy condition for WHERE clause

        Example:
            >>> name_col = LocaleFieldSelector.select_field(Model, "name", "ko")
            >>> condition = SearchPatternBuilder.build_search_condition(name_col, "query")
            >>> statement = select(Model).where(condition)

        Notes:
            - Short queries (1-2 chars): ILIKE only
            - Long queries (3+ chars): ILIKE OR similarity > threshold
            - Trigram similarity threshold: 0.1 (optimized for Korean)
        """
        # Normalize query
        query = query.strip()

        if not query:
            # Empty query should match nothing
            # Use a condition that's always false
            return column.is_(None) & column.isnot(None)

        # Short query: ILIKE only
        if len(query) <= SearchPatternBuilder.SHORT_QUERY_THRESHOLD:
            return column.ilike(f"%{query}%")

        # Long query: ILIKE + similarity
        if use_trigram_similarity:
            return or_(
                column.ilike(f"%{query}%"),
                func.similarity(column, query)
                > SearchPatternBuilder.SIMILARITY_THRESHOLD,
            )
        else:
            return column.ilike(f"%{query}%")

    @staticmethod
    def build_order_by(
        column: ColumnElement[Optional[str]], query: str
    ) -> ColumnElement:
        """
        Build ORDER BY clause based on query length.

        Args:
            column: Column to order by
            query: Search query string

        Returns:
            SQLAlchemy order by expression

        Example:
            >>> order_by = SearchPatternBuilder.build_order_by(name_col, "test query")
            >>> statement = select(Model).where(...).order_by(order_by)

        Notes:
            - Short queries: Alphabetical ordering (column ASC)
            - Long queries: Similarity score DESC (best matches first)
        """
        query = query.strip()

        if len(query) <= SearchPatternBuilder.SHORT_QUERY_THRESHOLD:
            return column  # Alphabetical ordering
        else:
            return func.similarity(column, query).desc()

    @staticmethod
    def is_short_query(query: str) -> bool:
        """
        Check if query is considered short.

        Args:
            query: Search query string

        Returns:
            True if query length <= threshold, False otherwise

        Example:
            >>> SearchPatternBuilder.is_short_query("a")
            True
            >>> SearchPatternBuilder.is_short_query("abc")
            False
        """
        return len(query.strip()) <= SearchPatternBuilder.SHORT_QUERY_THRESHOLD


class QueryFilterBuilder:
    """
    Common filter building utilities.

    Provides standardized methods for applying common filters like:
    - Visibility filters (is_visible + User.is_admin)
    - ID exclusion filters
    - Null/empty checks
    """

    @staticmethod
    def add_visibility_filters(
        statement: "Select", model_with_visibility: type[SQLModel]
    ) -> "Select":
        """
        Add standard visibility filters (is_visible=True, is_admin=False).

        This helper automatically:
        1. Joins User table if not already joined
        2. Filters out admin users (User.is_admin == False)
        3. Filters to visible entities only (model.is_visible == True)

        Args:
            statement: Select statement to modify
            model_with_visibility: Model with is_visible field (Artist, Artwork, etc.)

        Returns:
            Modified statement with visibility filters

        Example:
            >>> statement = select(Model)
            >>> statement = QueryFilterBuilder.add_visibility_filters(statement, Model)
            >>> # Now includes: WHERE User.is_admin = false AND Model.is_visible = true

        Notes:
            - Requires model to have user_id field for User join
            - SQLAlchemy handles duplicate joins automatically
        """
        from backend.domain.user.model import User

        # Join User if not already joined
        # SQLAlchemy will handle duplicate joins automatically
        statement = statement.join(
            User, getattr(model_with_visibility, "user_id") == User.id
        )

        # Add filters
        statement = statement.where(
            User.is_admin.is_(False),  # Exclude admin users
            getattr(model_with_visibility, "is_visible"),  # Only visible entities
        )

        return statement

    @staticmethod
    def add_exclude_id_filter(
        statement: "Select", model: type[SQLModel], exclude_id: Optional[str]
    ) -> "Select":
        """
        Add exclude ID filter if provided.

        Args:
            statement: Select statement to modify
            model: SQLModel class
            exclude_id: Optional ID to exclude

        Returns:
            Modified statement (unchanged if exclude_id is None)

        Example:
            >>> statement = select(Model)
            >>> statement = QueryFilterBuilder.add_exclude_id_filter(
            ...     statement, Model, "id_123"
            ... )
            >>> # WHERE Model.id != 'id_123'
        """
        if exclude_id:
            statement = statement.where(getattr(model, "id") != exclude_id)
        return statement

    @staticmethod
    def add_not_null_and_not_empty_filter(
        statement: "Select", column: ColumnElement[Optional[str]]
    ) -> "Select":
        """
        Add filters for non-null and non-empty string values.

        Args:
            statement: Select statement to modify
            column: Column to check

        Returns:
            Modified statement with IS NOT NULL and != '' filters

        Example:
            >>> material_col = LocaleFieldSelector.select_field(Artwork, "material", "ko")
            >>> statement = select(Artwork)
            >>> statement = QueryFilterBuilder.add_not_null_and_not_empty_filter(
            ...     statement, material_col
            ... )
            >>> # WHERE material_ko IS NOT NULL AND material_ko != ''
        """
        statement = statement.where(column.isnot(None), column != "")
        return statement
