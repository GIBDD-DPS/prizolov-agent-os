"""Тесты для модуля Memory."""

import pytest
import json
import tempfile
from pathlib import Path
from prizolov_os.memory.memory import Memory, MemoryBackend


class TestMemoryInit:
    """Тесты инициализации памяти."""
    
    def test_memory_create_in_memory(self):
        """Создание in-memory памяти."""
        mem = Memory(backend="in_memory")
        assert mem.backend == MemoryBackend.IN_MEMORY
        assert len(mem) == 0
    
    def test_memory_create_json(self):
        """Создание JSON памяти."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            mem = Memory(backend="json", storage_path=temp_path)
            assert mem.backend == MemoryBackend.JSON
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_memory_create_sqlite(self):
        """Создание SQLite памяти."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            temp_path = f.name
        
        try:
            mem = Memory(backend="sqlite", storage_path=temp_path)
            assert mem.backend == MemoryBackend.SQLITE
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestMemoryStore:
    """Тесты метода store."""
    
    def test_store_valid_pair(self):
        """Сохранение валидной пары."""
        mem = Memory()
        mem.store("question", "answer")
        assert len(mem) == 1
        assert mem[0] == ("question", "answer")
    
    def test_store_multiple_pairs(self):
        """Сохранение нескольких пар."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        assert len(mem) == 2
    
    def test_store_strips_whitespace(self):
        """store должен обрезать пробелы."""
        mem = Memory()
        mem.store("  question  ", "  answer  ")
        assert mem[0] == ("question", "answer")
    
    def test_store_none_query(self):
        """None в query должен вызывать TypeError."""
        mem = Memory()
        with pytest.raises(TypeError):
            mem.store(None, "answer")
    
    def test_store_none_response(self):
        """None в response должен вызывать TypeError."""
        mem = Memory()
        with pytest.raises(TypeError):
            mem.store("question", None)
    
    def test_store_json_persistence(self):
        """JSON хранилище должно сохранять данные."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            mem = Memory(backend="json", storage_path=temp_path)
            mem.store("q1", "a1")
            mem.store("q2", "a2")
            
            # Пересоздаём память (должна загрузить из файла)
            mem2 = Memory(backend="json", storage_path=temp_path)
            assert len(mem2) == 2
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_store_sqlite_persistence(self):
        """SQLite хранилище должно сохранять данные."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            temp_path = f.name
        
        try:
            mem = Memory(backend="sqlite", storage_path=temp_path)
            mem.store("q1", "a1")
            mem.store("q2", "a2")
            
            # Пересоздаём память (должна загрузить из БД)
            mem2 = Memory(backend="sqlite", storage_path=temp_path)
            assert len(mem2) == 2
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestMemoryRetrieve:
    """Тесты метода retrieve."""
    
    def test_retrieve_empty_memory(self):
        """Поиск в пустой памяти."""
        mem = Memory()
        result = mem.retrieve("anything")
        assert result == ""
    
    def test_retrieve_found(self):
        """Поиск с найденным результатом."""
        mem = Memory()
        mem.store("привет мир", "здравствуйте")
        result = mem.retrieve("привет")
        assert "здравствуйте" in result
    
    def test_retrieve_not_found(self):
        """Поиск без результатов."""
        mem = Memory()
        mem.store("привет мир", "здравствуйте")
        result = mem.retrieve("несуществующий")
        assert result == ""
    
    def test_retrieve_empty_query(self):
        """Пустой запрос должен возвращать пустую строку."""
        mem = Memory()
        mem.store("test", "result")
        assert mem.retrieve("") == ""
    
    def test_retrieve_none_query(self):
        """None запрос должен возвращать пустую строку."""
        mem = Memory()
        mem.store("test", "result")
        assert mem.retrieve(None) == ""
    
    def test_retrieve_case_insensitive(self):
        """Поиск должен быть регистронезависимым."""
        mem = Memory()
        mem.store("Привет Мир", "Здравствуйте")
        result = mem.retrieve("привет")
        assert "Здравствуйте" in result


class TestMemoryClear:
    """Тесты метода clear."""
    
    def test_clear_empty_memory(self):
        """Очистка пустой памяти."""
        mem = Memory()
        mem.clear()
        assert len(mem) == 0
    
    def test_clear_filled_memory(self):
        """Очистка заполненной памяти."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        assert len(mem) == 2
        
        mem.clear()
        assert len(mem) == 0


class TestMemoryExportImport:
    """Тесты экспорта/импорта."""
    
    def test_export_json(self):
        """Экспорт в JSON."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            mem.export_json(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            assert len(data) == 2
            assert data[0]['query'] == "q1"
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_import_json(self):
        """Импорт из JSON."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
            temp_path = f.name
            json.dump([
                {'query': 'q1', 'response': 'a1'},
                {'query': 'q2', 'response': 'a2'}
            ], f)
        
        try:
            mem = Memory()
            count = mem.import_json(temp_path)
            
            assert count == 2
            assert len(mem) == 2
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestMemoryDelete:
    """Тесты метода delete."""
    
    def test_delete_found(self):
        """Удаление найденных записей."""
        mem = Memory()
        mem.store("привет 1", "ответ 1")
        mem.store("привет 2", "ответ 2")
        mem.store("пока", "ответ 3")
        
        deleted = mem.delete("привет")
        assert deleted == 2
        assert len(mem) == 1
    
    def test_delete_not_found(self):
        """Удаление несуществующих записей."""
        mem = Memory()
        mem.store("test", "result")
        
        deleted = mem.delete("несуществующий")
        assert deleted == 0
        assert len(mem) == 1


class TestMemoryIteration:
    """Тесты итерации."""
    
    def test_iterate(self):
        """Итерация по памяти."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        
        items = list(mem)
        assert len(items) == 2
        assert ("q1", "a1") in items
    
    def test_getitem(self):
        """Доступ по индексу."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        
        assert mem[0] == ("q1", "a1")
        assert mem[1] == ("q2", "a2")
    
    def test_len(self):
        """Длина памяти."""
        mem = Memory()
        assert len(mem) == 0
        
        mem.store("q1", "a1")
        assert len(mem) == 1
        
        mem.store("q2", "a2")
        assert len(mem) == 2
