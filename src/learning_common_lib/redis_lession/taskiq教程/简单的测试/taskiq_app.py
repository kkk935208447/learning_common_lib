# taskiq_app.py
import asyncio
import os
from taskiq_redis import ListQueueBroker

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:simple_test:taskiq_app",
)

# 创建 Redis Broker（任务队列）
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
)

# 定义任务 1：发送邮件
# taskiq 与celery不同，celery task_name有一套完整自动拼接逻辑，而taskiq的自动拼接容易出错。
# TaskIQ 中 task_name 必须在当前 broker 的任务注册表中保持唯一，且 producer / worker 两侧必须完全一致。对于会被直接运行的教程文件，建议显式指定稳定的 task_name，避免脚本作为 __main__ 运行时，默认 task_name 推导受启动方式影响。
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
# taskiq 与celery不同，celery task_name有一套完整自动拼接逻辑，而taskiq的自动拼接容易出错。
# TaskIQ 中 task_name 必须在当前 broker 的任务注册表中保持唯一，且 producer / worker 两侧必须完全一致。对于会被直接运行的教程文件，建议显式指定稳定的 task_name，避免脚本作为 __main__ 运行时，默认 task_name 推导受启动方式影响。
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
# taskiq 与celery不同，celery task_name有一套完整自动拼接逻辑，而taskiq的自动拼接容易出错。
# TaskIQ 中 task_name 必须在当前 broker 的任务注册表中保持唯一，且 producer / worker 两侧必须完全一致。对于会被直接运行的教程文件，建议显式指定稳定的 task_name，避免脚本作为 __main__ 运行时，默认 task_name 推导受启动方式影响。
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
