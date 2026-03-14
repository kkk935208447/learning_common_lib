# producer.py
import asyncio


# `from .taskiq_app import broker` 是显式相对导入：只有当 `worker.py` 被视为包里的模块时才成立。
# 也就是说，Python 需要知道它的 `__package__`（或 `__spec__`）是 `learning_common_lib.redis_lession.taskiq教程.简单的测试`才能把 `.` 解析成“同级包”。
# 当你直接 `python worker.py` 时，这个脚本处在裸运行环境，没有父包，`__package__ == None`，`.` 就无处可指，所以报错 “attempted relative import with no known parent package”，
# 本案例需要 cd learning_common_lib.redis_lession.taskiq教程 也就是父目录`简单的测试` 的同级目录，
# 使用 `python -m 简单的测试.worker` 才能正常运行（大型项目中推荐使用这种方案）
# 更简单的方法就是 使用 try-except 捕获 ImportError 异常，如下所示可以支持项目运行的相对导入，同时也支持 IDE 直接运行.py脚本时的绝对导入。

try:
    from .taskiq_app import send_email, process_data, heavy_calculation
except ImportError:
    # IDE直接运行.py脚本时，改为绝对导入，确保在任何环境下都能正常运行
    from taskiq_app import send_email, process_data, heavy_calculation


async def main():
    """
    生产者：发送任务到 Redis 队列
    """
    print("=" * 60)
    print("📤 生产者启动：发送任务到队列...")
    print("=" * 60)
    
    # 任务 1：发送邮件
    print("\n1️⃣ 发送邮件任务...")
    email_task = await send_email.kiq(
        recipient="user@example.com",
        subject="欢迎使用 TaskIQ",
        body="这是一封测试邮件"
    )
    print(f"   ✅ 任务已加入队列，Task ID: {email_task.task_id}")
    
    # 任务 2：处理数据
    print("\n2️⃣ 发送数据处理任务...")
    data_task = await process_data.kiq(
        data={"user_id": 123, "action": "login"}
    )
    print(f"   ✅ 任务已加入队列，Task ID: {data_task.task_id}")
    
    # 任务 3：计算任务
    print("\n3️⃣ 发送计算任务...")
    calc_task = await heavy_calculation.kiq(x=100, y=200)
    print(f"   ✅ 任务已加入队列，Task ID: {calc_task.task_id}")
    
    print("\n" + "=" * 60)
    print("✅ 所有任务已发送！请查看 Worker 控制台输出")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
