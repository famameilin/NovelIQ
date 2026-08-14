"""
工作流共享类型定义

2026-08-13 P2-5: 移除无使用点的 StreamEmitter Protocol。
所有工作流均直接使用 Callable[[StreamEvent], Awaitable[None]] 形式接收 emitter，
无任何代码引用本模块导出，删除后保留空模块以防外部工具按包扫描。
"""
