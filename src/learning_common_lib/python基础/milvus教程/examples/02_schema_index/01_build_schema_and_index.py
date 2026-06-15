"""
目标: 演示 Milvus collection 的 schema 与 index_params 如何在客户端构造
关键 API: MilvusClient.create_schema, DataType, prepare_index_params, add_index
本例重点参数:
- create_schema(auto_id, enable_dynamic_field): 控制主键是否自增、是否允许未声明字段进入动态 metadata。
- schema.add_field(field_name, datatype, is_primary, max_length, dim): 定义字段名、字段类型、主键、字符串长度和向量维度。
- add_index(field_name, index_type, metric_type, params): 指定向量字段、索引类型、相似度度量和构建参数。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/02_schema_index/01_build_schema_and_index.py
预期现象: 打印字段名称、向量维度、索引类型和度量方式
生产提醒: collection 加载前必须有向量索引；教程优先使用官方推荐的 AUTOINDEX
"""

from pymilvus import DataType, MilvusClient


def main() -> None:
    dimension = 8
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimension)
    schema.add_field("text", DataType.VARCHAR, max_length=1024)
    schema.add_field("source", DataType.VARCHAR, max_length=128)
    schema.add_field("chunk_no", DataType.INT64)

    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    fields = [field.name for field in schema.fields]
    vector_field = next(field for field in schema.fields if field.name == "vector")
    index_config = list(index_params)[0]
    index_dict = index_config.to_dict()

    print(f"fields={fields}")
    print(f"vector_dim={vector_field.params['dim']}")
    print(f"index_field={index_config.field_name}")
    print(f"index_type={index_config.index_type}")
    print(f"metric_type={index_dict['metric_type']}")


if __name__ == "__main__":
    main()
