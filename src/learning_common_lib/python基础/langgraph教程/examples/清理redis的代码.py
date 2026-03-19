"""
多个example会使用到不同的DB，可能会产生一些干扰，有需要时可以清空所有DB
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