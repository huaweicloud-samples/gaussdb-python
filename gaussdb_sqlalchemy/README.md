# GaussDB SQLAlchemy Dialect

SQLAlchemy dialect for Huawei GaussDB, built on the `gaussdb` (psycopg3 fork) driver.

## 前置条件

- Python 3.7+
- GaussDB libpq (Linux: 运行 `tools/install_gaussdb_driver.sh`)
- `gaussdb` Python 包 (psycopg3 fork)

## 安装

```bash
pip install gaussdb-sqlalchemy
```

## 连接

```python
from sqlalchemy import create_engine

engine = create_engine(
    "gaussdb://user:password@host:port/dbname?sslmode=disable"
)
```

也支持显式指定驱动：

```python
engine = create_engine(
    "gaussdb+psycopg://user:password@host:port/dbname?sslmode=disable"
)
```

## 兼容模式

驱动自动检测数据库的兼容模式并适配 SQL 方言：

| 特性 | A 兼容 (Oracle) | B 兼容 (MySQL) | M 兼容 (MySQL) |
|------|----------------|----------------|----------------|
| 标识符引号 | 双引号 | 双引号/反引号 | 反引号 |
| 自增主键 | serial | serial/AUTO_INCREMENT | AUTO_INCREMENT |
| ORM INSERT 获取自增 ID | RETURNING | RETURNING | LAST_INSERT_ID() |
| 字符串拼接 | \|\| | \|\| | CONCAT() |
| TIMESTAMP 精度 | 默认无 | 默认无 | TIMESTAMP(6) |
| Oracle 语法 (DUAL/NVL/SYSDATE) | 支持 | 支持 | 不支持 |

## 许可证

LGPL-3.0
