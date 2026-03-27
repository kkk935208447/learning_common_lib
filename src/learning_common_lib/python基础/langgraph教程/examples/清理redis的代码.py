"""
多个example会使用到不同的DB，可能会产生一些干扰，有需要时可以清空所有DB

目标:
    多个example会使用到不同的DB，可能会产生一些干扰，有需要时可以清空所有DB

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/清理redis的代码.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/清理redis的代码.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
import redis as redis_lib
def reset_tutorial_redis() -> None:
    """清空教程专用 Redis DB，避免示例之间互相污染。"""
    for db in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15):
        client = redis_lib.Redis(
            host="localhost",
            port=6379,
            password="123456",
            db=db,
            socket_connect_timeout=3,
        )
        try:
            client.flushdb()
        finally:
            print(f"DB {db} 已清空")
            client.close()
    print("所有 DB 已清空")

if __name__ == "__main__":
    reset_tutorial_redis()
