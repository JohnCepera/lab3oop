"""
Лабораторная работа № 3. Система логирования.

Реализация на Python с использованием Protocol, композиции и агрегации.
Запуск демонстрации: python lab3_logging.py
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import socket
from datetime import datetime
from enum import Enum
from ftplib import FTP
from typing import Iterable, Protocol


class LogLevel(Enum):
    """Уровни логирования."""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Протоколы
# ---------------------------------------------------------------------------

class LogFilterProtocol(Protocol):
    def match(self, log_level: LogLevel, text: str) -> bool:
        """Возвращает True, если сообщение проходит фильтр."""
        ...


class LogHandlerProtocol(Protocol):
    def handle(self, log_level: LogLevel, text: str) -> None:
        """Передаёт сообщение соответствующему получателю."""
        ...


class LogFormatterProtocol(Protocol):
    def format(self, log_level: LogLevel, text: str) -> str:
        """Возвращает отформатированное сообщение."""
        ...


# ---------------------------------------------------------------------------
# Фильтры
# ---------------------------------------------------------------------------

class SimpleLogFilter:
    """Пропускает сообщения, содержащие заданную текстовую подстроку."""

    def __init__(self, pattern: str, case_sensitive: bool = True) -> None:
        self.pattern = pattern
        self.case_sensitive = case_sensitive

    def match(self, log_level: LogLevel, text: str) -> bool:
        if self.case_sensitive:
            return self.pattern in text
        return self.pattern.casefold() in text.casefold()


class ReLogFilter:
    """Пропускает сообщения, в которых найдено совпадение с regex."""

    def __init__(self, pattern: str, flags: int = 0) -> None:
        self.pattern = pattern
        self._regex = re.compile(pattern, flags)

    def match(self, log_level: LogLevel, text: str) -> bool:
        return self._regex.search(text) is not None


class LevelFilter:
    """Пропускает только указанные уровни логирования."""

    def __init__(self, levels: LogLevel | Iterable[LogLevel]) -> None:
        if isinstance(levels, LogLevel):
            self.levels = {levels}
        else:
            self.levels = set(levels)

        if not self.levels:
            raise ValueError("Нужно указать хотя бы один уровень логирования.")
        if not all(isinstance(level, LogLevel) for level in self.levels):
            raise TypeError("Все уровни должны быть значениями LogLevel.")

    def match(self, log_level: LogLevel, text: str) -> bool:
        return log_level in self.levels


# ---------------------------------------------------------------------------
# Форматтеры
# ---------------------------------------------------------------------------

class StandardLogFormatter:
    """Форматирует запись как [LEVEL] [yyyy.MM.dd HH:mm:ss] text."""

    def format(self, log_level: LogLevel, text: str) -> str:
        timestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        return f"[{log_level.value}] [{timestamp}] {text}"


# ---------------------------------------------------------------------------
# Обработчики
# ---------------------------------------------------------------------------

class ConsoleHandler:
    """Выводит сообщения в консоль."""

    def handle(self, log_level: LogLevel, text: str) -> None:
        print(text)


class FileHandler:
    """Записывает сообщения в текстовый файл."""

    def __init__(self, filename: str, encoding: str = "utf-8") -> None:
        self.filename = filename
        self.encoding = encoding

    def handle(self, log_level: LogLevel, text: str) -> None:
        with open(self.filename, "a", encoding=self.encoding) as file:
            file.write(text + "\n")


class SocketHandler:
    """Отправляет сообщение TCP-сокету.

    Сообщение отправляется в UTF-8 и завершается символом новой строки.
    Соединение открывается для каждой записи. Сервер должен принимать TCP
    подключения на указанных host и port.
    """

    def __init__(self, host: str, port: int, timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def handle(self, log_level: LogLevel, text: str) -> None:
        payload = (text + "\n").encode("utf-8")
        with socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        ) as connection:
            connection.sendall(payload)


class SyslogHandler:
    """Отправляет сообщения системному журналу через SysLog."""

    def __init__(
        self,
        address: str | tuple[str, int] = "/dev/log",
        facility: int = logging.handlers.SysLogHandler.LOG_USER,
    ) -> None:
        self._handler = logging.handlers.SysLogHandler(
            address=address, facility=facility
        )

    def handle(self, log_level: LogLevel, text: str) -> None:
        priority = {
            LogLevel.INFO: logging.INFO,
            LogLevel.WARN: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
        }[log_level]
        record = logging.LogRecord(
            name="LabLogger",
            level=priority,
            pathname="",
            lineno=0,
            msg=text,
            args=(),
            exc_info=None,
        )
        self._handler.emit(record)

    def close(self) -> None:
        self._handler.close()


class FtpHandler:
    """Добавляет сообщение в файл на FTP-сервере.

    Параметры подключения задаются при создании объекта. На каждую запись
    открывается отдельное FTP-соединение; команда APPE добавляет строку
    в конец удалённого файла, если сервер поддерживает APPE.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        remote_path: str,
        port: int = 21,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.remote_path = remote_path
        self.port = port
        self.timeout = timeout

    def handle(self, log_level: LogLevel, text: str) -> None:
        from io import BytesIO

        payload = BytesIO((text + "\n").encode("utf-8"))
        with FTP() as ftp:
            ftp.connect(self.host, self.port, timeout=self.timeout)
            ftp.login(self.username, self.password)
            ftp.storbinary(f"APPE {self.remote_path}", payload)


# ---------------------------------------------------------------------------
# Logger: композиция фильтров, форматтеров и обработчиков
# ---------------------------------------------------------------------------

class Logger:
    def __init__(
        self,
        filters: Iterable[LogFilterProtocol] | None = None,
        formatters: Iterable[LogFormatterProtocol] | None = None,
        handlers: Iterable[LogHandlerProtocol] | None = None,
    ) -> None:
        # Logger хранит ссылки на переданные объекты — агрегация.
        self.filters = list(filters) if filters is not None else []
        self.formatters = list(formatters) if formatters is not None else []
        self.handlers = list(handlers) if handlers is not None else []

    def log(self, log_level: LogLevel, text: str) -> None:
        if not isinstance(log_level, LogLevel):
            raise TypeError("log_level должен быть значением LogLevel.")
        if not isinstance(text, str):
            raise TypeError("Текст сообщения должен быть строкой.")

        # Сообщение должно пройти все заданные фильтры.
        if not all(log_filter.match(log_level, text)
                   for log_filter in self.filters):
            return

        formatted_text = text
        # Форматтеры применяются последовательно.
        for formatter in self.formatters:
            formatted_text = formatter.format(log_level, formatted_text)

        # Одна и та же готовая запись передаётся всем обработчикам.
        for handler in self.handlers:
            handler.handle(log_level, formatted_text)

    def log_info(self, text: str) -> None:
        self.log(LogLevel.INFO, text)

    def log_warn(self, text: str) -> None:
        self.log(LogLevel.WARN, text)

    def log_error(self, text: str) -> None:
        self.log(LogLevel.ERROR, text)


def main() -> None:
    """Демонстрация работы фильтров, форматтера и нескольких обработчиков."""

    logger = Logger(
        filters=[
            # Пропускаем только INFO, WARN и ERROR (все три уровня).
            LevelFilter([LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR]),
            # Пропускаем сообщения, в которых есть одно из слов:
            # ошибка, предупреждение или запуск.
            ReLogFilter(r"ошибка|предупреждение|запуск", flags=re.IGNORECASE),
        ],
        formatters=[StandardLogFormatter()],
        handlers=[
            ConsoleHandler(),
            FileHandler("application.log"),
        ],
    )

    logger.log_info("Запуск приложения.")
    logger.log_warn("Предупреждение: проверьте настройки.")
    logger.log_error("Ошибка: файл не найден.")
    logger.log_info("Это сообщение не пройдёт фильтр.")

    print("\nДемонстрация завершена. Логи также записаны в application.log.")


if __name__ == "__main__":
    main()
