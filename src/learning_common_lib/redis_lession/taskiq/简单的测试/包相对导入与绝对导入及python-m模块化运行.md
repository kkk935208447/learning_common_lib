# 包相对导入，与 python -m 模块运行

**User**

请问 from .taskiq_app import broker  与 from taskiq_app import broker 导入的区别是什么，我cd到 src/learning_common_lib/redis_lession/taskiq/简单的测试 路径下，python taskiq_app.py 时 from taskiq_app import broker 这种导入可以工作， from .taskiq_app import broker 不能工作


**回答**

`from taskiq_app import broker` 是绝对导入：Python 会在 `sys.path` 里按顺序找名为 `taskiq_app` 的模块。你 `cd` 到 `src/.../简单的测试` 后运行 `python worker.py`，这个目录正好在 `sys.path` 首位（当前工作目录），所以 Python 能直接把同目录下的 `taskiq_app.py` 当作顶层模块加载，不依赖包上下文。

`from .taskiq_app import broker` 是显式相对导入：只有当 `worker.py` 被视为包里的模块时才成立。也就是说，Python 需要知道它的 `__package__`（或 `__spec__`）是 `learning_common_lib.redis_lession.taskiq.简单的测试`，才能把 `.` 解析成“同级包”。当你直接 `python worker.py` 时，这个脚本处在裸运行环境，没有父包，`__package__ == None`，`.` 就无处可指，所以报错 “attempted relative import with no known parent package”，本案例需要 cd `learning_common_lib.redis_lession.taskiq` 也就是父目录`简单的测试` 的同级目录，使用 `python -m 简单的测试.worker` 才能正常运行（推荐使用这种方案）

总结：

- 绝对导入依赖 `sys.path`，不要求包结构，但可能引入同名模块冲突。
- 相对导入依赖包上下文，写法更清晰，但必须通过包方式加载（`python -m package.module` 或从包外部导入）。


详情见 `根目录下`的 `docs/python模块化运行与脚本运行的区别.md` 文件


# 