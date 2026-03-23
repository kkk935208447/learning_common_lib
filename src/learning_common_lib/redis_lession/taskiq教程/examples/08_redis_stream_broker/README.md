# RedisStreamBroker 小章节

这一小章节专门讲 `RedisStreamBroker`，目标不是只给你一个能跑的 demo，而是把以下问题拆开讲清楚：

1. Redis Stream 和 Redis List 的底层行为到底差在哪
2. `RedisStreamBroker` 为什么比 `ListQueueBroker` 更接近“生产级可靠队列”
3. 当前 `taskiq==0.12.0`、`taskiq-redis==1.1.2` 下，TaskIQ 的“单 broker + 动态 queue_name 路由”应该怎么理解

推荐阅读顺序：

1. `01_stream_data_structure_basics.py`
   用原生 Redis 命令视角看 `XADD` / `XGROUP CREATE` / `XREADGROUP` / `XACK`
2. `02_list_vs_stream_reliability.py`
   直接对比 `ListQueueBroker` 背后的 `LPUSH/BRPOP` 与 Stream 的 ACK / pending / reclaim
3. `03_taskiq_redis_stream_hello.py`
   最小 TaskIQ + `RedisStreamBroker` 可运行示例
4. `04_single_broker_dynamic_queue_name.py`
   演示“一个 broker 对象 + 动态 `queue_name` + `additional_streams`”这条新路线

本地版本核对：

- `taskiq==0.12.0`
- `taskiq-redis==1.1.2`

关键事实：

- 当前本地 `taskiq worker --help` 没有 Celery 那样的 `--queue/--queues`
- 所以 TaskIQ 的“多队列”在当前版本里更准确地说是：
  - 通过不同 broker 入口隔离不同 queue/stream
  - 或者通过一个 `RedisStreamBroker` 的 `queue_name + additional_streams` 同时监听多个 stream
- producer 侧动态路由依赖的不是 CLI，而是 message labels 里的 `queue_name`
