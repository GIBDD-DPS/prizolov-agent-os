"""
Модуль памяти для Prizolov Agent OS.

Поддерживает:
- In-memory хранение (быстро, для тестов)
- JSON файл (просто, для разработки)
- SQLite база данных (надёжно, для продакшена)
"""

import json
import sqlite3
from typing import List, Tuple, Optional
from pathlib import Path
from enum import Enum


class MemoryBackend(Enum):
    """Типы бэкендов памяти."""
    IN_MEMORY = "in_memory"
    JSON = "json"
    SQLITE = "sqlite"


class Memory:
    """
    Система памяти для хранения истории взаимодействий.
    
    Примеры использования:
        # In-memory (по умолчанию)
        mem = Memory()
        
        # JSON файл
        mem = Memory(backend="json", storage_path="data/memory.json")
        
        # SQLite база данных
        mem = Memory(backend="sqlite", storage_path="data/memory.db")
    """
    
    def __init__(
        self,
        backend: str = "in_memory",
        storage_path: Optional[str] = None
    ) -> None:
        """
        Инициализация памяти.
        
        Args:
            backend: Тип хранилища ("in_memory", "json", "sqlite")
            storage_path: Путь к файлу/БД (обязательно для json/sqlite)
        """
        self.backend = MemoryBackend(backend)
        self.storage_path: Optional[Path] = Path(storage_path) if storage_path else None
        
        # In-memory данные (используются всегда для кэша)
        self._data: List[Tuple[str, str]] = []
        
        # Инициализация бэкенда
        if self.backend == MemoryBackend.JSON:
            self._init_json()
        elif self.backend == MemoryBackend.SQLITE:
            self._init_sqlite()
    
    def _init_json(self) -> None:
        """Инициализация JSON хранилища."""
        if self.storage_path:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_json()
    
    def _init_sqlite(self) -> None:
        """Инициализация SQLite хранилища."""
        if self.storage_path:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._create_sqlite_table()
            self._load_sqlite()
    
    def _load_json(self) -> None:
        """Загрузка данных из JSON файла."""
        if self.storage_path and self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._data = [(item['query'], item['response']) for item in data]
            except (json.JSONDecodeError, KeyError) as e:
                self._data = []
    
    def _save_json(self) -> None:
        """Сохранение данных в JSON файл."""
        if self.storage_path:
            data = [
                {'query': q, 'response': r, 'timestamp': None}
                for q, r in self._data
            ]
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _create_sqlite_table(self) -> None:
        """Создание таблицы SQLite."""
        if self.storage_path:
            conn = sqlite3.connect(str(self.storage_path))
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_query ON memory(query)')
            conn.commit()
            conn.close()
    
    def _load_sqlite(self) -> None:
        """Загрузка данных из SQLite."""
        if self.storage_path:
            conn = sqlite3.connect(str(self.storage_path))
            cursor = conn.cursor()
            cursor.execute('SELECT query, response FROM memory ORDER BY id')
            self._data = [(row[0], row[1]) for row in cursor.fetchall()]
            conn.close()
    
    def _save_sqlite_entry(self, query: str, response: str) -> None:
        """Сохранение одной записи в SQLite."""
        if self.storage_path:
            conn = sqlite3.connect(str(self.storage_path))
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO memory (query, response) VALUES (?, ?)',
                (query, response)
            )
            conn.commit()
            conn.close()
    
    def store(self, query: str, response: str) -> None:
        """
        Сохраняет пару запрос-ответ в память.
        
        Args:
            query: Текст запроса
            response: Текст ответа
            
        Raises:
            TypeError: Если query или response не строки
        """
        if not isinstance(query, str):
            raise TypeError(f"Query must be str, got {type(query).__name__}")
        if not isinstance(response, str):
            raise TypeError(f"Response must be str, got {type(response).__name__}")
        
        query = query.strip()
        response = response.strip()
        
        # Добавляем в кэш
        self._data.append((query, response))
        
        # Сохраняем в бэкенд
        if self.backend == MemoryBackend.JSON:
            self._save_json()
        elif self.backend == MemoryBackend.SQLITE:
            self._save_sqlite_entry(query, response)
    
    def retrieve(self, query: str) -> str:
        """
        Поиск по памяти.
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Найденные ответы (через пробел) или пустая строка
        """
        if not query or not isinstance(query, str):
            return ""
        
        keywords = query.strip().split()
        if not keywords:
            return ""
        
        first_keyword = keywords[0].lower()
        results = [
            response for stored_query, response in self._data
            if first_keyword in stored_query.lower()
        ]
        
        return " ".join(results)
    
    def retrieve_all(self, query: str) -> List[Tuple[str, str]]:
        """
        Поиск по памяти с возвратом всех совпадений.
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Список кортежей (запрос, ответ)
        """
        if not query or not isinstance(query, str):
            return []
        
        keywords = query.strip().split()
        if not keywords:
            return []
        
        first_keyword = keywords[0].lower()
        return [
            (stored_query, response) for stored_query, response in self._data
            if first_keyword in stored_query.lower()
        ]
    
    def clear(self) -> None:
        """Очищает всю память."""
        self._data = []
        
        if self.backend == MemoryBackend.JSON:
            self._save_json()
        elif self.backend == MemoryBackend.SQLITE:
            if self.storage_path:
                conn = sqlite3.connect(str(self.storage_path))
                cursor = conn.cursor()
                cursor.execute('DELETE FROM memory')
                conn.commit()
                conn.close()
    
    def delete(self, query: str) -> int:
        """
        Удаляет записи по запросу.
        
        Args:
            query: Запрос для удаления
            
        Returns:
            Количество удалённых записей
        """
        if not query or not isinstance(query, str):
            return 0
        
        keyword = query.strip().lower()
        original_len = len(self._data)
        
        self._data = [
            (q, r) for q, r in self._data
            if keyword not in q.lower()
        ]
        
        deleted_count = original_len - len(self._data)
        
        if self.backend == MemoryBackend.JSON:
            self._save_json()
        elif self.backend == MemoryBackend.SQLITE:
            if self.storage_path:
                conn = sqlite3.connect(str(self.storage_path))
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM memory WHERE query LIKE ?',
                    (f'%{query}%',)
                )
                conn.commit()
                conn.close()
        
        return deleted_count
    
    def __len__(self) -> int:
        """Возвращает количество записей в памяти."""
        return len(self._data)
    
    def __iter__(self):
        """Итератор по записям памяти."""
        return iter(self._data)
    
    def __getitem__(self, index: int) -> Tuple[str, str]:
        """Доступ к записи по индексу."""
        return self._data[index]
    
    def export_json(self, filepath: str) -> None:
        """
        Экспортирует память в JSON файл.
        
        Args:
            filepath: Путь к файлу для экспорта
        """
        data = [
            {'query': q, 'response': r}
            for q, r in self._data
        ]
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def import_json(self, filepath: str) -> int:
        """
        Импортирует память из JSON файла.
        
        Args:
            filepath: Путь к файлу для импорта
            
        Returns:
            Количество импортированных записей
        """
        path = Path(filepath)
        if not path.exists():
            return 0
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        count = 0
        for item in data:
            if 'query' in item and 'response' in item:
                self.store(item['query'], item['response'])
                count += 1
        
        return count
