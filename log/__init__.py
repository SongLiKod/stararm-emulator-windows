"""系统日志模块：系统日志、运行日志、错误日志三类，支持双语词条与界面监听。"""
from log.logger import LogLevel, LogEntry, StarARMLogger, get_logger

__all__ = ["LogLevel", "LogEntry", "StarARMLogger", "get_logger"]
