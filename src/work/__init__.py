"""
work 队列机制包

进程内的任务运行态与队列写回——任务缓存与在飞协程（task_manager）、运行态持久化
（task_persistence）、阶段进度事件（events）、日志与产物清理（artifacts）。
驱动本包的是编排层（src/workflows），api 不直接依赖本包。
本包不维护 re-export 面，消费者按子模块路径导入。
"""
