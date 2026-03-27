"""Тесты для модуля Memory."""

import pytest
from prizolov_os.memory.memory import Memory


class TestMemoryInit:
    """Тесты инициализации памяти."""
    
    def test_memory_create_empty(self):
        """Создание пустой памяти."""
        mem = Memory()
        assert mem.data == []
        assert len(mem) == 0


class TestMemoryStore:
    """Тесты метода store."""
    
    def test_store_valid_pair(self):
        """Сохранение валидной пары."""
        mem = Memory()
        mem.store("question", "answer")
        assert len(mem) == 1
        assert mem.data[0] == ("question", "answer")
    
    def test_store_multiple_pairs(self):
        """Сохранение нескольких пар."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        assert len(mem) == 2
    
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
        assert mem.retrieve("") == ""
    
    def test_retrieve_none_query(self):
        """None запрос должен возвращать пустую строку."""
        mem = Memory()
        mem.store("test", "result")
        assert mem.retrieve(None) == ""


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
        mem.clear()
        assert len(mem) == 0


class TestMemoryLen:
    """Тесты метода __len__."""
    
    def test_len_empty(self):
        """Длина пустой памяти."""
        mem = Memory()
        assert len(mem) == 0
    
    def test_len_after_stores(self):
        """Длина после сохранений."""
        mem = Memory()
        mem.store("q1", "a1")
        mem.store("q2", "a2")
        assert len(mem) == 2
