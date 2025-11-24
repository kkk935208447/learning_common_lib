# producer.py
import asyncio
from .taskiq_app import send_email, process_data, heavy_calculation


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