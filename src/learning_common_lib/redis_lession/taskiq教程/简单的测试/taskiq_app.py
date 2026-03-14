# taskiq_app.py
import asyncio
from taskiq_redis import ListQueueBroker

# 创建 Redis Broker（任务队列）
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
)

# 定义任务 1：发送邮件
@broker.task(task_name="简单的测试.taskiq_app.send_email")
async def send_email(recipient: str, subject: str, body: str) -> str:
    """
    模拟发送邮件任务
    """
    print(f"📧 [Worker] 开始发送邮件...")
    print(f"   收件人: {recipient}")
    print(f"   主题: {subject}")
    print(f"   内容: {body}")
    
    # 模拟耗时操作
    await asyncio.sleep(3)
    
    result = f"✅ 邮件已发送至 {recipient}"
    print(result)
    return result


# 定义任务 2：处理数据
@broker.task(task_name="简单的测试.taskiq_app.process_data")
async def process_data(data: dict) -> dict:
    """
    模拟数据处理任务
    """
    print(f"🔄 [Worker] 开始处理数据: {data}")
    
    await asyncio.sleep(2)
    
    result = {
        "status": "processed",
        "original": data,
        "processed_at": "2024-11-24 18:30:00"
    }
    
    print(f"✅ [Worker] 数据处理完成: {result}")
    return result


# 定义任务 3：计算任务
@broker.task(task_name="简单的测试.taskiq_app.heavy_calculation")
async def heavy_calculation(x: int, y: int) -> int:
    """
    模拟重计算任务
    """
    print(f"🧮 [Worker] 开始计算 {x} + {y}")
    await asyncio.sleep(1)
    result = x + y
    print(f"✅ [Worker] 计算结果: {result}")
    return result
