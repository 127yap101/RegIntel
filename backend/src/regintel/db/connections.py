"""Trusted application wiring for connections and transactional completion hooks."""

from collections.abc import Callable

from regintel.db.migrations import DatabaseConnection

type ConnectionFactory = Callable[[], DatabaseConnection]
type CompletionHook[T] = Callable[[DatabaseConnection, T], None]
