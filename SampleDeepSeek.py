from typing import Any, Optional, Dict, Union, SupportsInt, SupportsFloat
from datetime import datetime
from pathlib import Path


class Log:
    # ... 其他代码保持不变 ...

    def get_log_files(self) -> list:
        """获取所有日志文件列表"""
        log_files = []
        for ext in ['*.log', '*.json', '*.gz', '*.zip']:
            for file in self.log_dir.glob(ext):
                try:
                    stat = file.stat()
                    log_files.append({
                        "name": file.name,
                        "path": str(file.absolute()),
                        "size": stat.st_size,
                        "size_human": self._human_readable_size(stat.st_size),
                        "modified": datetime.fromtimestamp(stat.st_mtime),
                        "created": datetime.fromtimestamp(stat.st_ctime)
                    })
                except (OSError, FileNotFoundError):
                    continue

        # 修复排序：明确指定返回类型为datetime
        log_files.sort(key=lambda x: x["modified"], reverse=True)
        return log_files

    # 或者使用类型明确的排序函数
    def get_log_files_fixed(self) -> list[Dict[str, Any]]:
        """修复类型检查问题的版本"""
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

    # 或者使用更严格类型提示的版本
    def get_log_files_strict(self) -> list[Dict[str, Union[str, int, datetime]]]:
        """严格类型提示版本"""
        from typing import TypedDict

        class LogFileInfo(TypedDict):
            name: str
            path: str
            size: int
            size_human: str
            modified: datetime
            created: datetime

        log_files: list[LogFileInfo] = []

        for ext in ['*.log', '*.json', '*.gz', '*.zip']:
            for file in self.log_dir.glob(ext):
                try:
                    stat = file.stat()
                    log_file_info: LogFileInfo = {
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

        # 使用类型明确的lambda
        log_files.sort(key=lambda x: x["modified"].timestamp(), reverse=True)
        return log_files