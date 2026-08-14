import argparse
import re
import socket
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import uvicorn
from loguru import logger

from src.config.logging_setup import setup_logging  # noqa: E402

ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi_codes(text: str) -> str:
    """去除 ANSI 颜色代码"""
    return ANSI_ESCAPE_PATTERN.sub('', text)


class TeeOutput:
    """同时输出到终端和文件，并在写文件前去掉 ANSI 颜色代码"""
    
    def __init__(self, original_stream, log_file_path: Path):
        self.original_stream = original_stream
        self.log_file = open(log_file_path, "a", encoding="utf-8")
    
    def write(self, message: str) -> None:
        self.original_stream.write(message)
        self.original_stream.flush()
        clean_message = strip_ansi_codes(message)
        self.log_file.write(clean_message)
        self.log_file.flush()
    
    def flush(self) -> None:
        self.original_stream.flush()
        self.log_file.flush()
    
    def isatty(self) -> bool:
        return self.original_stream.isatty()
    
    def fileno(self) -> int:
        return self.original_stream.fileno()
    
    def close(self) -> None:
        self.log_file.close()


def is_port_in_use(port: int) -> bool:
    """检测指定端口是否已被当前机器占用"""
    for check_host in ["127.0.0.1", "0.0.0.0"]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((check_host, port))
            except OSError:
                return True
    return False


def main() -> None:
    """启动 FastAPI 服务器并记录控制台输出"""
    parser = argparse.ArgumentParser(description="Run FastAPI server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument(
        "--app",
        type=str,
        default="src.api.main:app",
        help="FastAPI app import path (default: src.api.main:app)",
    )
    args = parser.parse_args()

    if is_port_in_use(args.port):
        print(f"\033[91m错误: 端口 {args.port} 已被占用，请使用其他端口或关闭占用该端口的进程。\033[0m")
        print("提示: 使用 --port 参数指定其他端口，例如: python scripts/run_api.py --port 8001")
        sys.exit(1)

    project_root = Path(__file__).resolve().parents[1]
    logs_dir = project_root / "logs"
    console_log_dir = logs_dir / "console"
    console_log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    console_log_file = console_log_dir / f"console_{timestamp}.log"
    all_log_file = logs_dir / "api.log"
    
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    tee_stdout = TeeOutput(original_stdout, console_log_file)
    tee_stderr = TeeOutput(original_stderr, console_log_file)
    
    sys.stdout = tee_stdout
    sys.stderr = tee_stderr
    
    setup_logging()
    
    logger.info(f"终端日志文件: {console_log_file}")
    logger.info(f"完整日志文件: {all_log_file}")

    try:
        uvicorn.run(
            args.app,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    except OSError as e:
        if "Address already in use" in str(e) or "Only one usage of each socket address" in str(e):
            print(f"\033[91m错误: 端口 {args.port} 已被占用: {e}\033[0m")
            sys.exit(1)
        raise
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        tee_stdout.close()
        tee_stderr.close()


if __name__ == "__main__":
    main()
