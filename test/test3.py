from contextvars import ContextVar
import uuid
import asyncio


context_var_id: ContextVar[str] = ContextVar("test", default="默认")

async def put_context_var():
    uuid_str = str(uuid.uuid4())
    context_var_id.set(uuid_str)
    await asyncio.sleep(2)
    return uuid_str

async def get_context_var(uuid_str):
    assert uuid_str == context_var_id.get()
    return uuid_str
    

async def test_context_var():
    uuid_str = await put_context_var()
    uuid_str = await get_context_var(uuid_str)
    return uuid_str


async def multi_run():
    tasks = [test_context_var() for _ in range(5)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    print(results)
    return results

if __name__ == "__main__":
    asyncio.run(multi_run())
