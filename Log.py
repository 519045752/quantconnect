import json
from dataclasses import is_dataclass, asdict

from loguru import logger
import sys
import os
from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from pathlib import Path
import shutil


class Log:
    """
    增强版日志类，支持：
    1. 控制台彩色输出
    2. 本地文件持久化
    3. 结构化日志格式
    4. 日志轮转和保留策略
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 env: str = "dev",
                 log_dir: str = "./logs",
                 log_level: str = "DEBUG",
                 rotation: str = "10 MB",  # 日志轮转大小
                 retention: str = "30 days",  # 日志保留时间
                 compression: str = "zip",  # 压缩格式
                 log_to_file: bool = True,  # 是否写入文件
                 max_log_files: int = 30):  # 最大日志文件数
        """
        初始化日志配置

        Args:
            env: 环境名称 (dev/test/prod)
            log_dir: 日志目录
            log_level: 日志级别 DEBUG/INFO/WARNING/ERROR
            rotation: 日志轮转条件 "10 MB", "1 day", "00:00"
            retention: 日志保留时间 "10 days", "1 month"
            compression: 压缩格式 "zip", "gz", None
            log_to_file: 是否写入文件
            max_log_files: 最大日志文件数（超过时自动清理）
        """
        if not hasattr(self, '_initialized'):  # 防止重复初始化
            self.env = env
            self.log_dir = Path(log_dir)
            self.log_level = log_level
            self.max_log_files = max_log_files

            # 解析保留时间
            self.retention_days = self._parse_retention(retention)

            # 确保日志目录存在
            self._ensure_log_dir()

            # 移除默认配置
            logger.remove()

            # 配置控制台输出
            self._setup_console()

            # 配置文件输出
            if log_to_file:
                self._setup_file_output(rotation, retention, compression)

            # 绑定logger上下文
            self._logger = logger.bind(
                name=self.__class__.__name__,
                env=self.env,
                timestamp=datetime.now().isoformat()
            )

            self._initialized = True
            # 记录初始化日志
            self._logger.info(f"日志系统初始化完成 - 环境: {env}, 级别: {log_level}")

    def get_logger(self, name: str = None):
        """获取指定名称的logger"""
        if name:
            return self._logger.bind(name=name, env=self.env)
        return self._logger

    def _parse_retention(self, retention_str: str) -> int:
        """解析保留时间字符串为天数"""
        try:
            if "day" in retention_str:
                days = int(retention_str.split()[0])
            elif "month" in retention_str:
                months = int(retention_str.split()[0])
                days = months * 30
            elif "week" in retention_str:
                weeks = int(retention_str.split()[0])
                days = weeks * 7
            else:
                days = 30  # 默认30天
            return days
        except:
            return 30

    def _ensure_log_dir(self):
        """确保日志目录存在"""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            print(f"✓ 日志目录已创建: {self.log_dir.absolute()}")
        except Exception as e:
            print(f"✗ 创建日志目录失败: {e}")
            raise

    def _setup_console(self):
        """配置控制台彩色输出"""
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[name]}</cyan> | "
            "<magenta>{extra[env]}</magenta> | "
            "<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )

        logger.add(
            sys.stdout,
            format=console_format,
            level=self.log_level,
            colorize=True,
            backtrace=True,  # 显示异常回溯
            diagnose=True,  # 显示变量值
            filter=self._console_filter
        )

    def _console_filter(self, record):
        """控制台过滤器（可以过滤敏感信息）"""
        # 示例：控制台不显示DEBUG级别的日志
        if self.env == "prod" and record["level"].name == "DEBUG":
            return False
        return True

    def _setup_file_output(self, rotation: str, retention: str, compression: str):
        """配置文件输出"""

        # 1. 所有日志的文件（包含DEBUG级别）
        all_logs_file = self.log_dir / f"{self.env}_all.log"
        self._add_file_handler(
            filepath=all_logs_file,
            level="DEBUG",  # 记录所有级别
            rotation=rotation,
            retention=retention,  # 直接使用传入的retention字符串
            compression=compression,
            format=self._get_file_format(include_extra=True)
        )

        # 2. 错误日志文件（只记录WARNING及以上）
        error_logs_file = self.log_dir / f"{self.env}_error.log"
        # 错误日志保留更久：如果传入的是"30 days"，这里使用"60 days"
        error_retention = self._get_extended_retention(retention)
        self._add_file_handler(
            filepath=error_logs_file,
            level="WARNING",  # 只记录警告和错误
            rotation=rotation,
            retention=error_retention,  # 错误日志保留更久
            compression=compression,
            format=self._get_file_format(include_extra=True)
        )

        # 3. JSON格式日志（便于ELK等系统分析）
        if self.env != "dev":  # 生产环境使用JSON格式
            json_logs_file = self.log_dir / f"{self.env}_structured.json"
            self._add_file_handler(
                filepath=json_logs_file,
                level="INFO",
                rotation=rotation,
                retention=retention,
                compression=compression,
                format=self._get_json_format(),
                serialize=True  # 自动序列化为JSON
            )

    def _get_extended_retention(self, retention: str) -> str:
        """延长保留时间（用于错误日志）"""
        try:
            if "day" in retention:
                days = int(retention.split()[0])
                return f"{days * 2} days"
            elif "month" in retention:
                months = int(retention.split()[0])
                return f"{months * 2} months"
            elif "week" in retention:
                weeks = int(retention.split()[0])
                return f"{weeks * 2} weeks"
            else:
                return "60 days"  # 默认60天
        except:
            return "60 days"

    def _add_file_handler(self, filepath: Path, **kwargs):
        """添加文件处理器"""
        try:
            logger.add(
                str(filepath),
                encoding="utf-8",
                enqueue=True,  # 线程安全
                **kwargs
            )
            print(f"✓ 日志文件已配置: {filepath.name}")
        except Exception as e:
            print(f"✗ 配置日志文件失败 {filepath.name}: {e}")
            # 如果失败，尝试使用默认参数
            self._add_file_handler_fallback(filepath)

    def _add_file_handler_fallback(self, filepath: Path):
        """备用的文件处理器配置（简化版）"""
        try:
            logger.add(
                str(filepath),
                encoding="utf-8",
                enqueue=True,
                rotation="10 MB",
                retention="30 days",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
            )
            print(f"✓ 使用备用配置成功: {filepath.name}")
        except Exception as e:
            print(f"✗ 备用配置也失败 {filepath.name}: {e}")

    def _get_file_format(self, include_extra: bool = True) -> str:
        """获取文件日志格式"""
        base_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{extra[name]} | "
            "{extra[env]} | "
            "{process} | "
            "{thread} | "
            "{module}.{function}:{line} | "
            "{message}"
        )

        if include_extra:
            base_format += " | {extra}"

        return base_format

    def _get_json_format(self):
        """获取JSON格式"""

        def json_formatter(record):
            """自定义JSON格式化器"""
            log_entry = {
                "timestamp": record["time"].isoformat(),
                "level": record["level"].name,
                "logger": record["extra"].get("name", ""),
                "env": record["extra"].get("env", ""),
                "message": record["message"],
                "module": record["module"],
                "function": record["function"],
                "line": record["line"],
                "process_id": record["process"].id,
                "thread_id": record["thread"].id,
                "file": record["file"].path if record["file"] else None
            }

            # 添加额外字段
            extra = {k: v for k, v in record["extra"].items()
                     if k not in ["name", "env"] and not k.startswith('_')}
            if extra:
                log_entry["extra"] = extra

            # 异常信息
            if record["exception"]:
                log_entry["exception"] = {
                    "type": record["exception"].type.__name__,
                    "value": str(record["exception"].value),
                    "traceback": "".join(record["exception"].traceback.format())
                }

            return json.dumps(log_entry, ensure_ascii=False) + "\n"

        return json_formatter

    def _format_message(self, obj: Any, title: Optional[str] = None) -> str:
        """格式化消息为字符串"""
        try:
            if isinstance(obj, (dict, list)):
                # 尝试JSON格式化
                formatted = json.dumps(obj, indent=4, ensure_ascii=False)
                if title:
                    return f"{title}:\n{formatted}"
                return formatted
            elif is_dataclass(obj) and not isinstance(obj, type):
                # 尝试JSON格式化
                formatted = json.dumps(asdict(obj), indent=4, ensure_ascii=False)
                if title:
                    return f"{title}:\n{formatted}"
                return formatted
            elif isinstance(obj, Exception):
                # 异常对象
                return f"Exception: {type(obj).__name__}: {str(obj)}"
            else:
                # 其他类型转为字符串
                result = str(obj)
                if title:
                    return f"{title}: {result}"
                return result
        except Exception as e:
            # 格式化失败时的备选方案
            return f"[格式化失败] {repr(obj)[:200]}..."

    def debug(self, obj: Any, title: Optional[str] = None, **kwargs):
        """调试日志"""
        message = self._format_message(obj, title)
        self._log_with_context("debug", message, **kwargs)

    def info(self, obj: Any, title: Optional[str] = None, **kwargs):
        """信息日志"""
        message = self._format_message(obj, title)
        self._log_with_context("info", message, **kwargs)

    def success(self, obj: Any, title: Optional[str] = None, **kwargs):
        """成功日志"""
        message = self._format_message(obj, title)
        self._log_with_context("success", message, **kwargs)

    def warning(self, obj: Any, title: Optional[str] = None, **kwargs):
        """警告日志"""
        message = self._format_message(obj, title)
        self._log_with_context("warning", message, **kwargs)

    def error(self, obj: Any, title: Optional[str] = None, **kwargs):
        """错误日志"""
        message = self._format_message(obj, title)
        self._log_with_context("error", message, **kwargs)

    def critical(self, obj: Any, title: Optional[str] = None, **kwargs):
        """严重错误日志"""
        message = self._format_message(obj, title)
        self._log_with_context("critical", message, **kwargs)

    def exception(self, obj: Any, title: Optional[str] = None, **kwargs):
        """异常日志（自动包含堆栈跟踪）"""
        message = self._format_message(obj, title)
        self._log_with_context("error", message, exc_info=True, **kwargs)

    def _log_with_context(self, level: str, message: str, **kwargs):
        """带上下文的日志记录"""
        # 创建带上下文的logger
        context_logger = self._logger.bind(**kwargs)

        # 调用对应级别的方法
        log_method = getattr(context_logger, level)
        log_method(message)

    def bind(self, **kwargs):
        """绑定持久化上下文"""
        self._logger = self._logger.bind(**kwargs)
        return self

    def patch(self, **kwargs):
        """临时修改上下文"""
        return self._logger.patch(lambda record: record["extra"].update(kwargs))

    def get_log_files_fixed(self) -> list[Dict[str, Any]]:

        log_files: list[Dict[str, Any]] = []

        for ext in ['*.log', '*.json', '*.gz', '*.zip']:
            for file in self.log_dir.glob(ext):
                try:
                    stat = file.stat()
                    log_file_info = {
                        "name": file.name,
                        "path": str(file.absolute()),
                        "size": stat.st_size,
                        "size_human": self._human_readable_size(stat.st_size),
                        "modified": datetime.fromtimestamp(stat.st_mtime),
                        "created": datetime.fromtimestamp(stat.st_ctime)
                    }
                    log_files.append(log_file_info)
                except (OSError, FileNotFoundError):
                    continue

        # 使用明确的排序函数
        def get_modified_time(item: Dict[str, Any]) -> datetime:
            """明确的排序键函数"""
            return item["modified"]

        log_files.sort(key=get_modified_time, reverse=True)
        return log_files

    def _human_readable_size(self, size_bytes: int) -> str:
        """将字节数转换为可读格式"""
        if size_bytes == 0:
            return "0B"

        units = ['B', 'KB', 'MB', 'GB', 'TB']
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {units[i]}"

    def cleanup_old_logs(self, days: Optional[int] = None):
        """清理旧日志文件"""
        if days is None:
            days = self.retention_days

        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0
        total_freed = 0

        for ext in ['*.log', '*.json', '*.gz', '*.zip']:
            for file in self.log_dir.glob(ext):
                try:
                    stat = file.stat()
                    if stat.st_mtime < cutoff_date.timestamp():
                        file_size = stat.st_size
                        file.unlink()
                        deleted_count += 1
                        total_freed += file_size
                        self.info(f"删除旧日志文件: {file.name} ({self._human_readable_size(file_size)})")
                except Exception as e:
                    self.error(f"删除日志文件失败 {file.name}: {e}")

        if deleted_count > 0:
            self.info(f"日志清理完成: 删除 {deleted_count} 个文件，释放 {self._human_readable_size(total_freed)}")

        return deleted_count

    def cleanup_by_count(self, keep_count: Optional[int] = None):
        """按文件数量清理（保留最新的N个）"""
        if keep_count is None:
            keep_count = self.max_log_files

        # 获取所有日志文件
        all_files = []
        for ext in ['*.log', '*.json', '*.gz', '*.zip']:
            for file in self.log_dir.glob(ext):
                try:
                    stat = file.stat()
                    all_files.append((file, stat.st_mtime, stat.st_size))
                except:
                    continue

        # 按修改时间排序
        all_files.sort(key=lambda x: x[1], reverse=True)

        # 删除超出数量的文件
        deleted_count = 0
        total_freed = 0

        if len(all_files) > keep_count:
            for file, _, file_size in all_files[keep_count:]:
                try:
                    file.unlink()
                    deleted_count += 1
                    total_freed += file_size
                    self.info(f"删除超出数量日志: {file.name}")
                except Exception as e:
                    self.error(f"删除日志文件失败 {file.name}: {e}")

        if deleted_count > 0:
            self.info(f"按数量清理完成: 删除 {deleted_count} 个文件，释放 {self._human_readable_size(total_freed)}")

        return deleted_count

    def get_log_summary(self) -> Dict:
        """获取日志统计信息"""
        total_size = 0
        file_count = 0
        by_type = {}

        for file in self.log_dir.iterdir():
            if file.is_file():
                try:
                    size = file.stat().st_size
                    total_size += size
                    file_count += 1

                    # 按类型统计
                    ext = file.suffix.lower()
                    if ext in by_type:
                        by_type[ext]["count"] += 1
                        by_type[ext]["size"] += size
                    else:
                        by_type[ext] = {"count": 1, "size": size}
                except:
                    continue

        return {
            "total_files": file_count,
            "total_size": total_size,
            "total_size_human": self._human_readable_size(total_size),
            "log_dir": str(self.log_dir.absolute()),
            "env": self.env,
            "level": self.log_level,
            "by_type": by_type
        }


log = Log()
# ============ 使用示例 ============
# if __name__ == "__main__":
#     print("=== 测试修复后的日志系统 ===")
#
#     # 测试标准配置
#     log = Log()
#
#     # 测试各种日志级别
#     log.debug("调试信息")
#     log.info({"status": "ok", "data": "测试"}, "接口响应")
#     log.warning("警告信息")
#     log.error("错误信息")
#
#     # 测试异常日志
#     try:
#         x = 1 / 0
#     except Exception as e:
#         log.exception("除零错误", e)
#
#     # 查看统计信息
#     print("\n=== 日志统计 ===")
#     summary = log.get_log_summary()
#     print(f"日志目录: {summary['log_dir']}")
#     print(f"文件总数: {summary['total_files']}")
#     print(f"总大小: {summary['total_size_human']}")
